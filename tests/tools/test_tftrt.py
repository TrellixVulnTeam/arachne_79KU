import os
import subprocess
import sys
import tarfile
import tempfile

import numpy as np
import pytest
import tensorflow as tf

from arachne.tools.tftrt import TFTRT, TFTRTConfig
from arachne.utils.model_utils import init_from_dir
from arachne.utils.tf_utils import make_tf_gpu_usage_growth


def create_dummy_representative_dataset():
    datasets = []
    shape = [1, 224, 224, 3]
    dtype = "float32"
    for _ in range(100):
        datasets.append(np.random.rand(*shape).astype(np.dtype(dtype)))  # type: ignore

    np.save("dummy.npy", datasets)


def check_tftrt_output(tf_model, input_shape, precision, tftrt_model_path):
    input_data = np.array(np.random.random_sample(input_shape), dtype=np.float32)  # type: ignore
    dout = tf_model(input_data).numpy()  # type: ignore

    loaded = tf.saved_model.load(tftrt_model_path)

    infer = loaded.signatures["serving_default"]  # type: ignore
    aout = infer(tf.constant(input_data))["predictions"].numpy()

    if precision == "FP32":
        np.testing.assert_allclose(aout, dout, atol=1e-5, rtol=1e-5)  # type: ignore
    elif precision == "FP16":
        np.testing.assert_allclose(aout, dout, atol=0.1, rtol=0)  # type: ignore
    elif precision == "INT8":
        # skip dummy int8
        pass


@pytest.mark.parametrize("precision", ["FP32", "FP16", "INT8"])
def test_tftrt(precision):
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        model = tf.keras.applications.mobilenet.MobileNet()
        model.save("saved_model")

        input_model = init_from_dir("saved_model")
        cfg = TFTRTConfig()
        cfg.precision_mode = precision
        if precision == "INT8":
            create_dummy_representative_dataset()
            cfg.representative_dataset = "dummy.npy"

        output = TFTRT.run(input_model, cfg)
        check_tftrt_output(model, [1, 224, 224, 3], precision, output.path)


def test_cli():
    # Due to the test time, we only test one case
    make_tf_gpu_usage_growth()

    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        model = tf.keras.applications.mobilenet.MobileNet()
        model.save("saved_model")

        ret = subprocess.run(
            [
                sys.executable,
                "-m",
                "arachne.driver.cli",
                "+tools=tftrt",
                "model_dir=saved_model",
                "output_path=output.tar",
            ]
        )

        assert ret.returncode == 0

        model_path = None
        with tarfile.open("output.tar", "r:gz") as tar:
            for m in tar.getmembers():
                if m.name.endswith("saved_model"):
                    model_path = m.name
            def is_within_directory(directory, target):
                
                abs_directory = os.path.abspath(directory)
                abs_target = os.path.abspath(target)
            
                prefix = os.path.commonprefix([abs_directory, abs_target])
                
                return prefix == abs_directory
            
            def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
            
                for member in tar.getmembers():
                    member_path = os.path.join(path, member.name)
                    if not is_within_directory(path, member_path):
                        raise Exception("Attempted Path Traversal in Tar File")
            
                tar.extractall(path, members, numeric_owner=numeric_owner) 
                
            
            safe_extract(tar, ".")

        assert model_path is not None
        check_tftrt_output(model, [1, 224, 224, 3], "FP32", model_path)
