import os
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict

import numpy as np
import onnxruntime as ort
import torch
import torchvision
import yaml

from arachne.data import Model, ModelFormat, ModelSpec, TensorSpec
from arachne.tools.torch2onnx import Torch2ONNX, Torch2ONNXConfig


def check_torch2onnx_output(torch_model, input_shape, onnx_model_path):
    input_data = np.array(np.random.random_sample(input_shape), dtype=np.float32)  # type: ignore
    torch_model.eval()
    torch_input = torch.from_numpy(input_data).clone()
    dout = torch_model(torch_input).to("cpu").detach().numpy().copy()

    sess = ort.InferenceSession(onnx_model_path, providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    aout = sess.run(output_names=None, input_feed={input_name: input_data})[0]
    np.testing.assert_allclose(aout, dout, atol=1e-5, rtol=1e-5)  # type: ignore


def test_torch2onnx():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        resnet18 = torchvision.models.resnet18(pretrained=True)
        torch.save(resnet18, f="resnet18.pt")

        spec = ModelSpec(
            inputs=[TensorSpec(name="input0", shape=[1, 3, 224, 224], dtype="float32")],
            outputs=[TensorSpec(name="output0", shape=[1, 1000], dtype="float32")],
        )
        input_model = Model(path="resnet18.pt", format=ModelFormat.PYTORCH, spec=spec)
        cfg = Torch2ONNXConfig()
        output = Torch2ONNX.run(input_model, cfg)
        check_torch2onnx_output(resnet18, [1, 3, 224, 224], output.path)


def test_cli():
    # Due to the test time, we only test one case

    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        resnet18 = torchvision.models.resnet18(pretrained=True)
        model_path = "resnet18.pt"
        torch.save(resnet18, f=model_path)

        spec = ModelSpec(
            inputs=[TensorSpec(name="input0", shape=[1, 3, 224, 224], dtype="float32")],
            outputs=[TensorSpec(name="output0", shape=[1, 1000], dtype="float32")],
        )

        with open("spec.yaml", "w") as file:
            yaml.dump(asdict(spec), file)

        ret = subprocess.run(
            [
                sys.executable,
                "-m",
                "arachne.driver.cli",
                "+tools=torch2onnx",
                f"model_file={model_path}",
                "model_spec_file=spec.yaml",
                "output_path=output.tar",
            ]
        )

        assert ret.returncode == 0

        model_file = None
        with tarfile.open("output.tar", "r:gz") as tar:
            for m in tar.getmembers():
                if m.name.endswith(".onnx"):
                    model_file = m.name
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

        assert model_file is not None
        check_torch2onnx_output(resnet18, [1, 3, 224, 224], model_file)
