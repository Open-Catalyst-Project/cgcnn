import ase.io
import numpy as np
import torch
from ase.optimize import BFGS
from torch import nn

from bfgs_torch import BFGS as BFGS_torch
from bfgs_torch import TorchCalc
from ocpmodels.trainers import ForcesTrainer

task = {
    "dataset": "trajectory_lmdb",
    "description": "Regressing to energies and forces for a trajectory dataset",
    "labels": ["potential energy"],
    "metric": "mae",
    "type": "regression",
    "grad_input": "atomic forces",
    "relax_dataset": {
        "src": "/checkpoint/electrocatalysis/relaxations/features/init_to_relaxed/1k/train/"
    },
    "relaxation_steps": 300,
}

model = {
    "name": "schnet",
    "hidden_channels": 1024,
    "num_filters": 256,
    "num_interactions": 3,
    "num_gaussians": 200,
    "cutoff": 6.0,
    "use_pbc": False,
}

train_dataset = {
    "src": "/private/home/mshuaibi/baselines/ocpmodels/common/efficient_validation/train",
    "normalize_labels": False,
}

optimizer = {
    "batch_size": 32,
    "eval_batch_size": 32,
    "lr_gamma": 0.1,
    "lr_initial": 0.0003,
    "lr_milestones": [20, 30],
    "num_workers": 32,
    "max_epochs": 50,
    "warmup_epochs": 10,
    "warmup_factor": 0.2,
    "force_coefficient": 30,
    "criterion": nn.L1Loss(),
}

identifier = "debug"
trainer = ForcesTrainer(
    task=task,
    model=model,
    dataset=train_dataset,
    optimizer=optimizer,
    identifier=identifier,
    print_every=5,
    is_debug=True,
    seed=1,
)

trainer.load_pretrained(
    "/private/home/mshuaibi/baselines/expts/ocp_expts/pre_final/ocp20M_08_16/checkpoints/2020-08-16-21-53-06-ocp20Mv6_schnet_lr0.0001_ch1024_fltr256_gauss200_layrs3_pbc/checkpoint.pt"
)
trainer.validate_relaxation()
