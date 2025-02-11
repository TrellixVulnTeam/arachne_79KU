import os
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict

import numpy as np
import onnxruntime as ort
import tensorflow as tf
import yaml
from tvm.contrib.download import download

from arachne.data import ModelSpec, TensorSpec
from arachne.tools.openvino2tf import OpenVINO2TF, OpenVINO2TFConfig
from arachne.tools.openvino_mo import OpenVINOModelOptConfig, OpenVINOModelOptimizer
from arachne.utils.model_utils import init_from_file
from arachne.utils.tf_utils import make_tf_gpu_usage_growth


def check_openvino2tf_output(onnx_model_path, tf_model_path):
    tf_loaded = tf.saved_model.load(tf_model_path)
    resnet18_tf = tf_loaded.signatures["serving_default"]  # type: ignore

    input = np.random.rand(1, 3, 224, 224).astype(np.float32)  # type: ignore

    # onnx runtime
    sess = ort.InferenceSession(onnx_model_path, providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    dout = sess.run(output_names=None, input_feed={input_name: input})[0]

    # tf
    tf_input = tf.convert_to_tensor(np.transpose(input, (0, 2, 3, 1)))
    tf_result = resnet18_tf(tf_input)
    aout = tf_result["tf.identity"].numpy()

    np.testing.assert_allclose(aout, dout, atol=1e-5, rtol=1e-5)  # type: ignore


def test_openvino2tf():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)

        url = (
            "https://arachne-public-pkgs.s3.ap-northeast-1.amazonaws.com/models/test/resnet18.onnx"
        )

        onnx_model_path = "resnet18.onnx"
        download(url, onnx_model_path)

        input_model = init_from_file(onnx_model_path)
        m = OpenVINOModelOptimizer.run(input_model, OpenVINOModelOptConfig())
        m = OpenVINO2TF.run(m, OpenVINO2TFConfig())

        check_openvino2tf_output(onnx_model_path, m.path)


def test_cli():
    # Due to the test time, we only test one case

    make_tf_gpu_usage_growth()

    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        url = (
            "https://arachne-public-pkgs.s3.ap-northeast-1.amazonaws.com/models/test/resnet18.onnx"
        )

        onnx_model_path = "resnet18.onnx"
        download(url, onnx_model_path)

        ret = subprocess.run(
            [
                sys.executable,
                "-m",
                "arachne.driver.cli",
                "+tools=openvino_mo",
                "model_file=resnet18.onnx",
                "output_path=output.tar",
            ]
        )

        assert ret.returncode == 0

        model_path = None
        with tarfile.open("output.tar", "r:gz") as tar:
            for m in tar.getmembers():
                if m.name.endswith("_0"):
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

        spec = ModelSpec(
            inputs=[TensorSpec(name="input0", shape=[1, 3, 224, 224], dtype="float32")],
            outputs=[TensorSpec(name="output0", shape=[1, 1000], dtype="float32")],
        )

        with open("spec.yaml", "w") as file:
            yaml.dump(asdict(spec), file)

        ret2 = subprocess.run(
            [
                sys.executable,
                "-m",
                "arachne.driver.cli",
                "+tools=openvino2tf",
                f"model_dir={model_path}",
                "model_spec_file=spec.yaml",
                "output_path=output2.tar",
            ]
        )

        assert ret2.returncode == 0

        with tarfile.open("output2.tar", "r:gz") as tar:
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

        check_openvino2tf_output(onnx_model_path, model_path)
