"""Download BGE embedding model from ModelScope (国内源)."""
import os
import sys

print("=" * 50)
print("  从 ModelScope 下载 BAAI/bge-base-en-v1.5 模型")
print("=" * 50)
print()

# Step 1: 用 modelscope 下载模型文件
try:
    from modelscope import snapshot_download
except ImportError:
    print("正在安装 modelscope ...")
    os.system(f"{sys.executable} -m pip install modelscope -q")
    from modelscope import snapshot_download

print("正在下载模型（从 ModelScope 国内源）...")
model_dir = snapshot_download("BAAI/bge-base-en-v1.5")
print(f"模型已下载到: {model_dir}")
print()

# Step 2: 验证能正常加载
print("验证模型加载...")
from sentence_transformers import SentenceTransformer
model = SentenceTransformer(model_dir)
test = model.encode(["测试文本"])
print(f"验证通过! 输出维度: {test.shape}")
print()
print("=" * 50)
print(f"下载完成!")
print(f"模型路径: {model_dir}")
print(f"请将此路径配置到 config.py 的 EMBEDDING_MODEL 中")
print("=" * 50)
