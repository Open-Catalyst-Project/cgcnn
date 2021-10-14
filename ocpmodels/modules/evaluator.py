"""
Copyright (c) Facebook, Inc. and its affiliates.

This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
"""

from typing import List, Optional, Set

import numpy as np
import torch

from ocpmodels.datasets.embeddings import ATOMIC_NUMBER_LABELS

"""
An evaluation module for use with the OCP dataset and suite of tasks. It should
be possible to import this independently of the rest of the codebase, e.g:

```
from ocpmodels.modules import Evaluator

evaluator = Evaluator(task="is2re")
perf = evaluator.eval(prediction, target)
```

task: "s2ef", "is2rs", "is2re".

We specify a default set of metrics for each task, but should be easy to extend
to add more metrics. `evaluator.eval` takes as input two dictionaries, one for
predictions and another for targets to check against. It returns a dictionary
with the relevant metrics computed.
"""


class Evaluator:
    atomic_number_tasks = {
        "s2ef": {"forces_mae", "forces_cos"},
        "is2rs": set(),
        "is2re": set(),
    }
    task_metrics = {
        "s2ef": [
            "forcesx_mae",
            "forcesy_mae",
            "forcesz_mae",
            "forces_mae",
            "forces_cos",
            "forces_magnitude",
            "energy_mae",
            "energy_force_within_threshold",
        ],
        "is2rs": [
            "average_distance_within_threshold",
            "positions_mae",
            "positions_mse",
        ],
        "is2re": ["energy_mae", "energy_mse", "energy_within_threshold"],
    }

    task_attributes = {
        "s2ef": ["energy", "forces", "natoms"],
        "is2rs": ["positions", "cell", "pbc", "natoms"],
        "is2re": ["energy"],
    }

    task_primary_metric = {
        "s2ef": "energy_force_within_threshold",
        "is2rs": "average_distance_within_threshold",
        "is2re": "energy_mae",
    }

    def __init__(
        self,
        task=None,
        atomwise_metric_atoms: Optional[List[int]] = None,
        atomic_number_metrics: Optional[Set[str]] = None,
    ):
        """
        Creates a new Evaluator.

        Args:
            task: the current task, must be either s2ef, is2rs, or is2re.
            atomwise_metric_atoms: a list of atomic numbers that should be considered for atom-wise metrics.
            atomic_number_metrics: a set of metrics that should be tracked atom-wise.
        """
        assert task in ["s2ef", "is2rs", "is2re"]
        self.task = task
        self.metric_fn = self.task_metrics[task]

        self.atomic_number_map = (
            {
                atomic_number: ATOMIC_NUMBER_LABELS.get(
                    atomic_number, str(atomic_number)
                )
                for atomic_number in atomwise_metric_atoms
            }
            if atomwise_metric_atoms is not None
            else {}
        )
        self.atomic_number_metrics = (
            atomic_number_metrics
            if atomic_number_metrics is not None
            else self.atomic_number_tasks[self.task]
        )

    def _eval_metric_fn(
        self,
        fn,
        prediction,
        target,
        metrics,
        fn_prefix=None,
        numel: Optional[torch.Tensor] = None,
    ):
        res = eval(fn)(prediction, target)
        if numel is not None:
            res["numel"] = numel
            res["metric"] = res["total"] / res["numel"]

        # for atomwise metrics, we add a prefix to the metric name (e.g., "atomwise_19_forces_mae")
        fn_metric_name = f"{fn_prefix}{fn}" if fn_prefix else fn
        return self.update(fn_metric_name, res, metrics)

    def _eval_atomwise_metrics(
        self, fn, atomic_numbers, prediction, target, metrics
    ):
        assert atomic_numbers is not None

        metric_key = fn.split("_")[0]
        if metric_key.startswith("forces"):
            metric_key = "forces"
        assert metric_key == "forces" or metric_key == "energy"
        assert metric_key in prediction and metric_key in target

        # create a copy of prediction and target where the results are set to 0 for atoms that are not in atomic_numbers
        for atomic_number in self.atomic_number_map.keys():
            mask = atomic_numbers == atomic_number

            # we make copies of the dicts so we don't modify the original used for non-atomwise metrics.
            # this is because we're modifying the values of these dicts to ignore irrelevant atoms (for each iteration).
            prediction_copy = {**prediction}
            prediction_copy[metric_key] = prediction_copy[metric_key].clone()
            prediction_copy[metric_key][~mask] = 0

            target_copy = {**target}
            target_copy[metric_key] = target_copy[metric_key].clone()
            target_copy[metric_key][~mask] = 0

            metrics = self._eval_metric_fn(
                fn,
                prediction_copy,
                target_copy,
                metrics,
                fn_prefix=f"atomwise_{self.atomic_number_map[atomic_number]}_",
                numel=mask.sum().item() * 3,
            )

        return metrics

    def eval(self, prediction, target, prev_metrics={}, atomic_numbers=None):
        for attr in self.task_attributes[self.task]:
            assert attr in prediction
            assert attr in target
            assert prediction[attr].shape == target[attr].shape

        metrics = prev_metrics

        for fn in self.task_metrics[self.task]:
            metrics = self._eval_metric_fn(fn, prediction, target, metrics)

            # should we track atom-wise stats for this metric?
            if atomic_numbers is not None and fn in self.atomic_number_metrics:
                metrics = self._eval_atomwise_metrics(
                    fn, atomic_numbers, prediction, target, metrics
                )

        return metrics

    def update(self, key, stat, metrics):
        if key not in metrics:
            metrics[key] = {
                "metric": None,
                "total": 0,
                "numel": 0,
            }

        if isinstance(stat, dict):
            # If dictionary, we expect it to have `metric`, `total`, `numel`.
            metrics[key]["total"] += stat["total"]
            metrics[key]["numel"] += stat["numel"]
            metrics[key]["metric"] = (
                metrics[key]["total"] / metrics[key]["numel"]
            )
        elif isinstance(stat, float) or isinstance(stat, int):
            # If float or int, just add to the total and increment numel by 1.
            metrics[key]["total"] += stat
            metrics[key]["numel"] += 1
            metrics[key]["metric"] = (
                metrics[key]["total"] / metrics[key]["numel"]
            )
        elif torch.is_tensor(stat):
            raise NotImplementedError

        return metrics


def energy_mae(prediction, target):
    return absolute_error(prediction["energy"], target["energy"])


def energy_mse(prediction, target):
    return squared_error(prediction["energy"], target["energy"])


def forcesx_mae(prediction, target):
    return absolute_error(prediction["forces"][:, 0], target["forces"][:, 0])


def forcesx_mse(prediction, target):
    return squared_error(prediction["forces"][:, 0], target["forces"][:, 0])


def forcesy_mae(prediction, target):
    return absolute_error(prediction["forces"][:, 1], target["forces"][:, 1])


def forcesy_mse(prediction, target):
    return squared_error(prediction["forces"][:, 1], target["forces"][:, 1])


def forcesz_mae(prediction, target):
    return absolute_error(prediction["forces"][:, 2], target["forces"][:, 2])


def forcesz_mse(prediction, target):
    return squared_error(prediction["forces"][:, 2], target["forces"][:, 2])


def forces_mae(prediction, target):
    return absolute_error(prediction["forces"], target["forces"])


def forces_mse(prediction, target):
    return squared_error(prediction["forces"], target["forces"])


def forces_cos(prediction, target):
    return cosine_similarity(prediction["forces"], target["forces"])


def forces_magnitude(prediction, target):
    return magnitude_error(prediction["forces"], target["forces"], p=2)


def positions_mae(prediction, target):
    return absolute_error(prediction["positions"], target["positions"])


def positions_mse(prediction, target):
    return squared_error(prediction["positions"], target["positions"])


def energy_force_within_threshold(prediction, target):
    # Note that this natoms should be the count of free atoms we evaluate over.
    assert target["natoms"].sum() == prediction["forces"].size(0)
    assert target["natoms"].size(0) == prediction["energy"].size(0)

    # compute absolute error on per-atom forces and energy per system.
    # then count the no. of systems where max force error is < 0.03 and max
    # energy error is < 0.02.
    f_thresh = 0.03
    e_thresh = 0.02

    success, total = 0.0, target["natoms"].size(0)

    error_forces = torch.abs(target["forces"] - prediction["forces"])
    error_energy = torch.abs(target["energy"] - prediction["energy"])

    start_idx = 0
    for i, n in enumerate(target["natoms"]):
        if (
            error_energy[i] < e_thresh
            and error_forces[start_idx : start_idx + n].max() < f_thresh
        ):
            success += 1
        start_idx += n

    return {
        "metric": success / total,
        "total": success,
        "numel": total,
    }


def energy_within_threshold(prediction, target):
    # compute absolute error on energy per system.
    # then count the no. of systems where max energy error is < 0.02.
    e_thresh = 0.02
    error_energy = torch.abs(target["energy"] - prediction["energy"])

    success = (error_energy < e_thresh).sum().item()
    total = target["energy"].size(0)

    return {
        "metric": success / total,
        "total": success,
        "numel": total,
    }


def average_distance_within_threshold(prediction, target):
    pred_pos = torch.split(
        prediction["positions"], prediction["natoms"].tolist()
    )
    target_pos = torch.split(target["positions"], target["natoms"].tolist())

    mean_distance = []
    for idx, ml_pos in enumerate(pred_pos):
        mean_distance.append(
            np.mean(
                np.linalg.norm(
                    min_diff(
                        ml_pos.detach().cpu().numpy(),
                        target_pos[idx].detach().cpu().numpy(),
                        target["cell"][idx].detach().cpu().numpy(),
                        target["pbc"].tolist(),
                    ),
                    axis=1,
                )
            )
        )

    success = 0
    intv = np.arange(0.01, 0.5, 0.001)
    for i in intv:
        success += sum(np.array(mean_distance) < i)

    total = len(mean_distance) * len(intv)

    return {"metric": success / total, "total": success, "numel": total}


def min_diff(pred_pos, dft_pos, cell, pbc):
    pos_diff = pred_pos - dft_pos
    fractional = np.linalg.solve(cell.T, pos_diff.T).T

    for i, periodic in enumerate(pbc):
        # Yes, we need to do it twice
        if periodic:
            fractional[:, i] %= 1.0
            fractional[:, i] %= 1.0

    fractional[fractional > 0.5] -= 1

    return np.matmul(fractional, cell)


def cosine_similarity(prediction, target):
    error = torch.cosine_similarity(prediction, target)
    return {
        "metric": torch.mean(error).item(),
        "total": torch.sum(error).item(),
        "numel": error.numel(),
    }


def absolute_error(prediction, target):
    error = torch.abs(target - prediction)
    return {
        "metric": torch.mean(error).item(),
        "total": torch.sum(error).item(),
        "numel": prediction.numel(),
    }


def squared_error(prediction, target):
    error = (target - prediction) ** 2
    return {
        "metric": torch.mean(error).item(),
        "total": torch.sum(error).item(),
        "numel": prediction.numel(),
    }


def magnitude_error(prediction, target, p=2):
    assert prediction.shape[1] > 1
    error = torch.abs(
        torch.norm(prediction, p=p, dim=-1) - torch.norm(target, p=p, dim=-1)
    )
    return {
        "metric": torch.mean(error).item(),
        "total": torch.sum(error).item(),
        "numel": error.numel(),
    }
