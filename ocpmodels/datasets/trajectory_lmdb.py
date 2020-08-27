import glob
import json
import os
import pickle
import random
from collections import defaultdict

import lmdb
import numpy as np
import torch
from torch.utils.data import Dataset
from torch_geometric.data import Batch

from ocpmodels.common.registry import registry


@registry.register_dataset("trajectory_lmdb")
class TrajectoryLmdbDataset(Dataset):
    def __init__(self, config, transform=None):
        super(TrajectoryLmdbDataset, self).__init__()

        self.config = config

        self.db_paths = glob.glob(
            os.path.join(self.config["src"], "") + "*lmdb"
        )
        self.txt_paths = glob.glob(
            os.path.join(self.config["src"], "") + "*txt"
        )
        assert len(self.db_paths) > 0, "No LMDBs found in {}".format(
            self.config["src"]
        )

        envs = [
            self.connect_db(self.db_paths[i])
            for i in range(len(self.db_paths))
        ]

        self._keys = [
            [
                j
                for j in range(
                    pickle.loads(
                        envs[i].begin().get(f"length".encode("ascii"))
                    )
                )
            ]
            for i in range(len(self.db_paths))
        ]
        self._keylens = [len(k) for k in self._keys]
        self._keylen_cumulative = np.cumsum(self._keylens).tolist()

        self._system_samples = defaultdict(list)
        self._keyidx = 0
        for kidx, i in enumerate(self.txt_paths):
            with open(i, "r") as k:
                traj_steps = k.read().splitlines()[: self._keylens[kidx]]
            k.close()
            for idx, sample in enumerate(traj_steps):
                systemid = os.path.splitext(
                    os.path.basename(sample).split(",")[0]
                )[0]
                self._system_samples[systemid].append(self._keyidx)
                self._keyidx += 1

        self.transform = transform

        for i in range(len(envs)):
            envs[i].close()

    def __len__(self):
        return sum(self._keylens)

    def __getitem__(self, idx):
        # Figure out which db this should be indexed from.
        db_idx = 0
        for i in range(len(self._keylen_cumulative)):
            if self._keylen_cumulative[i] > idx:
                db_idx = i
                break

        # Extract index of element within that db.
        el_idx = idx
        if db_idx != 0:
            el_idx = idx - self._keylen_cumulative[db_idx - 1]
        assert el_idx >= 0

        # Return features.
        env = self.connect_db(self.db_paths[db_idx])
        datapoint_pickled = env.begin().get(
            f"{self._keys[db_idx][el_idx]}".encode("ascii")
        )
        data_object = pickle.loads(datapoint_pickled)
        data_object = (
            data_object
            if self.transform is None
            else self.transform(data_object)
        )
        env.close()

        return data_object

    def connect_db(self, lmdb_path=None):
        env = lmdb.open(
            lmdb_path,
            subdir=False,
            readonly=True,
            lock=False,
            readahead=False,
            map_size=1099511627776 / len(self.db_paths),
        )
        return env


def data_list_collater(data_list):
    n_neighbors = []
    for i, data in enumerate(data_list):
        n_index = data.edge_index[1, :]
        n_neighbors.append(n_index.shape[0])
    batch = Batch.from_data_list(data_list)
    batch.neighbors = torch.tensor(n_neighbors)
    return batch
