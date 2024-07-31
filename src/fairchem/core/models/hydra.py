from __future__ import annotations

import typing
from abc import ABCMeta, abstractmethod

import torch

if typing.TYPE_CHECKING:
    from torch_geometric.data.batch import Batch

from fairchem.core.common.registry import registry
from fairchem.core.models.base import BaseModel


class HeadInterface(metaclass=ABCMeta):
    @abstractmethod
    def forward(
        self, data: Batch, emb: dict[str, torch.Tensor]
    ) -> dict[str, torch.Tensor]:
        """Head forward.

        Arguments
        ---------
        data: DataBatch
            Atomic systems as input
        emb: dict[str->torch.Tensor]
            Embeddings of the input as generated by the backbone

        Returns
        -------
        outputs: dict[str->torch.Tensor]
            Return one or more targets generated by this head
        """
        return


class BackboneInterface(metaclass=ABCMeta):
    @abstractmethod
    def forward(self, data: Batch) -> dict[str, torch.Tensor]:
        """Backbone forward.

        Arguments
        ---------
        data: DataBatch
            Atomic systems as input

        Returns
        -------
        embedding: dict[str->torch.Tensor]
            Return backbone embeddings for the given input
        """
        return


@registry.register_model("base_hydra")
class BaseHydra(BaseModel):
    def __init__(
        self,
        backbone: dict,
        heads: dict,
        otf_graph: bool = True,
    ):
        super().__init__()
        self.otf_graph = otf_graph

        backbone_model_name = backbone.pop("model")
        self.backbone: BackboneInterface = registry.get_model_class(
            backbone_model_name
        )(
            **backbone,
        )

        # Iterate through outputs_cfg and create heads
        self.output_heads: dict[str, HeadInterface] = {}

        head_names_sorted = sorted(heads.keys())
        for head_name in head_names_sorted:
            head_config = heads[head_name]
            if "module" not in head_config:
                raise ValueError(
                    f"{head_name} head does not specify module to use for the head"
                )

            module_name = head_config.pop("module")
            self.output_heads[head_name] = registry.get_model_class(module_name)(
                self.backbone,
                backbone,
                head_config,
            )  # .to(self.backbone.device)

        self.output_heads = torch.nn.ModuleDict(self.output_heads)

    def forward(self, data: Batch):
        emb = self.backbone(data)
        # Predict all output properties for all structures in the batch for now.
        out = {}
        for k in self.output_heads:
            out.update(self.output_heads[k](data, emb))

        return out
