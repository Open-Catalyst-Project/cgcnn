"""
Copyright (c) Meta, Inc. and its affiliates.

This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import ase
import torch
from torch_scatter import scatter

if TYPE_CHECKING:
    from .optimizable import OptimizableBatch


class LBFGS:
    """Limited memory BFGS optimizer for batch ML relaxations."""

    def __init__(
        self,
        optimizable_batch: OptimizableBatch,
        maxstep: float = 0.01,
        memory: int = 100,
        damping: float = 0.25,
        alpha: float = 100.0,
        device: str = "cuda:0",
        save_full_traj: bool = True,
        traj_dir: Path | None = None,
        traj_names: list[str] | None = None,
        mask_converged: bool = True,
    ) -> None:
        """
        Args:
            optimizable_batch: an optimizable batch which includes a model and a batch of data
            maxstep: maximum number of steps to run optimization
            memory: Number of steps to be stored in memory
            damping: The calculated step is multiplied with this number before added to the positions.
            alpha: Initial guess for the Hessian (curvature of energy surface)
            device: device to run optimization on
            save_full_traj: wether to save full trajectory
            traj_dir: path to save trajectories in
            traj_names: list of trajectory files names
            mask_converged: whether to mask batches where all atoms are below convergence threshold
        """
        self.optimizable = optimizable_batch
        self.maxstep = maxstep
        self.memory = memory
        self.damping = damping
        self.alpha = alpha
        self.H0 = 1.0 / self.alpha
        self.device = device
        self.save_full = save_full_traj
        self.traj_dir = traj_dir
        self.traj_names = traj_names
        self.mask_converged = mask_converged
        self.otf_graph = optimizable_batch.trainer._unwrapped_model.otf_graph

        assert not self.traj_dir or (
            traj_dir and len(traj_names)
        ), "Trajectory names should be specified to save trajectories"
        logging.info("Step   Fmax(eV/A)")

        if not self.otf_graph and "edge_index" not in self.optimizable.batch:
            self.optimizable.update_graph()

    def set_positions(self, positions, update_mask):
        if self.mask_converged:
            positions = torch.where(update_mask.unsqueeze(1), positions, 0.0)

        self.optimizable.set_positions(positions.to(dtype=torch.float32))

        if not self.otf_graph:
            self.optimizable.update_graph()

    def check_convergence(self, iteration):
        energy = self.optimizable.get_potential_energies()

        # TODO check why forces are cast to float64
        forces = self.optimizable.get_forces(apply_constraint=True)
        forces = forces.to(dtype=torch.float64)

        max_forces = self.optimizable.get_max_forces()
        logging.info(
            f"{iteration} " + " ".join(f"{x:0.3f}" for x in max_forces.tolist())
        )

        # (batch_size) -> (nAtoms)
        max_forces = max_forces[self.optimizable.batch_indices]
        return max_forces.lt(self.fmax), energy, forces

    def run(self, fmax, steps):
        self.fmax = fmax
        self.steps = steps

        self.s = deque(maxlen=self.memory)
        self.y = deque(maxlen=self.memory)
        self.rho = deque(maxlen=self.memory)
        self.r0 = self.f0 = None

        self.trajectories = None
        if self.traj_dir:
            self.traj_dir.mkdir(exist_ok=True, parents=True)
            self.trajectories = [
                ase.io.Trajectory(self.traj_dir / f"{name}.traj_tmp", mode="w")
                for name in self.traj_names
            ]

        iteration = 0
        converged = False
        converged_mask = torch.zeros(
            self.optimizable.batch_indices.shape[0],
            dtype=torch.bool,
            device=self.device,
        )
        while iteration < steps and not converged:
            _converged_mask, energy, forces = self.check_convergence(iteration)
            # Models like GemNet-OC can have random noise in their predictions.
            # Here we ensure atom positions are not being updated after already
            # hitting the desired convergence criteria.
            converged_mask = torch.logical_or(converged_mask, _converged_mask)
            converged = torch.all(converged_mask)
            update_mask = torch.logical_not(converged_mask)

            if self.trajectories is not None and (
                self.save_full or converged or iteration == steps - 1 or iteration == 0
            ):
                # forces and mask can be augmented
                self.write(
                    energy,
                    forces[: self.optimizable.batch.pos.shape[0]],
                    update_mask[: self.optimizable.batch.pos.shape[0]],
                )

            if not converged and iteration < steps - 1:
                self.step(iteration, forces, update_mask)

            iteration += 1

        # GPU memory usage as per nvidia-smi seems to gradually build up as
        # batches are processed. This releases unoccupied cached memory.
        torch.cuda.empty_cache()

        if self.trajectories is not None:
            for traj in self.trajectories:
                traj.close()
            for name in self.traj_names:
                traj_fl = Path(self.traj_dir / f"{name}.traj_tmp", mode="w")
                traj_fl.rename(traj_fl.with_suffix(".traj"))

        self.optimizable.batch.energy = energy
        # forces are augmented
        self.optimizable.batch.forces = forces[: self.optimizable.batch.pos.shape[0]]

        return self.optimizable.batch

    def _determine_step(self, dr):
        steplengths = torch.norm(dr, dim=1)
        longest_steps = scatter(
            steplengths, self.optimizable.batch_indices, reduce="max"
        )
        longest_steps = longest_steps[self.optimizable.batch_indices]
        maxstep = longest_steps.new_tensor(self.maxstep)
        scale = (longest_steps + 1e-7).reciprocal() * torch.min(longest_steps, maxstep)
        dr *= scale.unsqueeze(1)
        return dr * self.damping

    def _batched_dot(self, x: torch.Tensor, y: torch.Tensor):
        return scatter(
            (x * y).sum(dim=-1), self.optimizable.batch_indices, reduce="sum"
        )

    def step(
        self,
        iteration: int,
        forces: torch.Tensor | None,
        update_mask: torch.Tensor,
    ) -> None:
        if forces is None:
            forces = self.optimizable.get_forces(apply_constraint=True)

        r = self.optimizable.get_positions().to(dtype=torch.float64)

        # Update s, y, rho
        if iteration > 0:
            s0 = r - self.r0
            self.s.append(s0)

            y0 = -(forces - self.f0)
            self.y.append(y0)

            self.rho.append(1.0 / self._batched_dot(y0, s0))

        loopmax = min(self.memory, iteration)
        alpha = forces.new_empty(loopmax, self.optimizable.batch.natoms.shape[0])
        q = -forces

        for i in range(loopmax - 1, -1, -1):
            alpha[i] = self.rho[i] * self._batched_dot(self.s[i], q)  # b
            q -= alpha[i][self.optimizable.batch_indices, ..., None] * self.y[i]

        z = self.H0 * q
        for i in range(loopmax):
            beta = self.rho[i] * self._batched_dot(self.y[i], z)
            z += self.s[i] * (
                alpha[i][self.optimizable.batch_indices, ..., None]
                - beta[self.optimizable.batch_indices, ..., None]
            )

        # descent direction
        p = -z
        dr = self._determine_step(p)
        if torch.abs(dr).max() < 1e-7:
            # Same configuration again (maybe a restart):
            return

        self.set_positions(r + dr, update_mask)

        self.r0 = r
        self.f0 = forces

    def write(self, energy, forces, update_mask) -> None:
        self.optimizable.batch.energy, self.optimizable.batch.forces = energy, forces
        atoms_objects = self.optimizable.get_atoms_list()
        update_mask_ = torch.split(update_mask, self.optimizable.batch.natoms.tolist())
        for atm, traj, mask in zip(atoms_objects, self.trajectories, update_mask_):
            if mask[0] or not self.save_full:
                traj.write(atm)
