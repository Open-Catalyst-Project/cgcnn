"""
Copyright (c) Meta, Inc. and its affiliates.

This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
"""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from typing import Union, List
    from torch_geometric.data import Data


def rename_data_object_keys(
    data_object: Data, key_mapping: dict[str, Union[str, List[str]]]
) -> Data:
    """Rename data object keys

    Args:
        data_object: data object
        key_mapping: dictionary specifying keys to rename and new names {prev_key: new_key}
    """
    for _property in key_mapping:
        # catch for test data not containing labels
        if _property in data_object:
            list_of_new_keys = key_mapping[_property]
            if type(list_of_new_keys) is str:
                list_of_new_keys = [list_of_new_keys]
            for new_property in list_of_new_keys:
                if new_property == _property:
                    continue
                assert new_property not in data_object
                data_object[new_property] = data_object[_property]
            if _property not in list_of_new_keys:
                del data_object[_property]
    return data_object
