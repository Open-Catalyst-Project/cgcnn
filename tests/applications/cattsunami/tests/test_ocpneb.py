import numpy as np
import pytest
from copy import deepcopy
from fairchem.applications.cattsunami.core import OCPNEB
from fairchem.core.common.relaxation.ase_utils import OCPCalculator
from ase.optimize import BFGS
from fairchem.core.models.model_registry import model_name_to_local_file

try:
    from ase.neb import DyNEB
except ImportError:  # newest unreleased version has changed imports
    from ase.mep.neb import DyNEB


@pytest.mark.usefixtures("neb_frames")
class TestNEB:
    @pytest.mark.parametrize(
        ("amp,tol"),
        [
            (False, 1e-4),
            (True, 1e-1),
        ],
    )
    def test_force_call(self, amp, tol, tmp_path):
        images = self.images.copy()
        checkpoint_path = model_name_to_local_file(
            "EquiformerV2-31M-S2EF-OC20-All+MD",
            local_cache=tmp_path / "ocp_checkpoints/",
        )
        batched = OCPNEB(
            images=images,
            checkpoint_path=checkpoint_path,
            cpu=True,
            batch_size=1,
            k=0.25,
            amp=amp,
        )

        for image in images[1:-1]:
            image.calc = OCPCalculator(
                checkpoint_path=checkpoint_path, cpu=True, amp=amp, seed=0
            )
        unbatched = DyNEB(images, k=0.25)

        forces = batched.get_forces()
        energies = batched.get_potential_energy()

        forces_ub = unbatched.get_forces()
        energies_ub = unbatched.get_potential_energy()

        mismatch = np.isclose(forces, forces_ub, atol=tol)
        assert np.isclose(energies, energies_ub, atol=tol).all()
        assert mismatch.all()

    def test_neb_call(self, tmp_path):
        images = deepcopy(self.images)
        checkpoint_path = model_name_to_local_file(
            "EquiformerV2-31M-S2EF-OC20-All+MD",
            local_cache=tmp_path / "ocp_checkpoints/",
        )
        batched = OCPNEB(
            images=images,
            checkpoint_path=checkpoint_path,
            cpu=True,
            batch_size=1,
            k=0.25,
            amp=False,
        )

        batched_opt = BFGS(batched, trajectory="batched.traj")
        batched_opt.run(fmax=0.05, steps=2)
        forces = batched.get_forces()
        energies = batched.get_potential_energy()

        images_ub = deepcopy(self.images)
        for image in images_ub[1:-1]:
            image.calc = OCPCalculator(
                checkpoint_path=checkpoint_path, cpu=True, amp=False
            )
        unbatched = DyNEB(images_ub, k=0.25)
        unbatched_opt = BFGS(unbatched, trajectory="unbatched.traj")
        unbatched_opt.run(fmax=0.05, steps=2)
        forces_ub = unbatched.get_forces()
        energies_ub = unbatched.get_potential_energy()

        mismatch = np.isclose(forces, forces_ub, atol=1e-3).all(axis=1)

        assert np.isclose(energies, energies_ub, atol=1e-3).all()
        assert mismatch.all()
