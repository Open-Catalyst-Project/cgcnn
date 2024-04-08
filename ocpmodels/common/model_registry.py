from __future__ import annotations

import logging
import os
import shutil
from importlib import resources

import urllib3
import yaml

from ocpmodels import models

with (resources.files(models) / "pretrained_models.yml").open("rt") as f:
    MODEL_REGISTRY = yaml.safe_load(f)


def model_name_to_local_file(model_name: str, local_cache: str) -> str | None:
    logging.info(f"Checking local cache: {local_cache} for model {model_name}")
    if model_name not in MODEL_REGISTRY:
        logging.error(f"Not a valid model name '{model_name}'")
        return None
    if not os.path.exists(local_cache):
        os.makedirs(local_cache, exist_ok=True)
    if not os.path.exists(local_cache):
        logging.error(f"Failed to create local cache folder '{local_cache}'")
        return None
    model_url = MODEL_REGISTRY[model_name]
    local_path = os.path.join(local_cache, os.path.basename(model_url))

    # download the file
    if not os.path.isfile(local_path):
        local_path_tmp = local_path + ".tmp"  # download to a tmp file in case we fail
        http = urllib3.PoolManager()
        with open(local_path_tmp, "wb") as out:
            r = http.request("GET", model_url, preload_content=False)
            shutil.copyfileobj(r, out)
        shutil.move(local_path_tmp, local_path)
    return local_path
