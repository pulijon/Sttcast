# 🛠️ Troubleshooting `whisperx` after System Update

## 📋 Context

For several months, I had been using [`whisperx`](https://github.com/m-bain/whisperx) for automatic audio transcription with good results. Previously, I used [`whisper`](https://github.com/openai/whisper) directly.

After a system update (likely on a **Debian testing or unstable** distribution), the transcription system stopped working correctly, throwing errors related to the loading of shared libraries.

---

## 🧨 Initial Problem

The error indicated that a library (`libctranslate2.so`) required an **executable stack**, which is **disabled by default in modern kernels for security reasons**.

```text
ImportError: libctranslate2.so.X.X.X: cannot enable executable stack as shared object requires: Invalid argument
```

This happened because `ctranslate2`, installed via `pip`, was **precompiled with an insecure ELF flag** (`PT_GNU_STACK` with executable permissions).

---

## 🧩 Resolution Strategy

### ✅ 1. Manual compilation of `ctranslate2`

To avoid relying on prebuilt binaries, I chose to:

- Compile `ctranslate2` manually from source
- Use the **exact version required by `whisperx`** (`v4.4.0`)
- Install it with:

  ```bash
  pip install . --no-build-isolation
  ```

### ⚠️ Issues encountered:

- The system compiler version (`gcc-14`) was **not compatible with `nvcc`** (from CUDA 12.2)
- A **controlled downgrade** was necessary for:
  - `gcc-11`, `g++-11`, `gcc-11-base`
  - `libstdc++-11-dev`, `libgcc-11-dev`, `cpp-11`, `libtsan0`
- `nvcc` was missing initially → resolved by installing `nvidia-cuda-toolkit`

### ✅ 2. Enabling GPU support

`CTranslate2` was recompiled with CUDA support:

```cmake
-DWITH_CUDA=ON
-DENABLE_CUDA_FP16=ON
```

However, when running `whisperx`, a new error appeared:

```text
RuntimeError: Conv1D on GPU currently requires the cuDNN library which is not integrated in this build
```

### ✅ 3. Installing cuDNN

- `.deb` packages for **cuDNN compatible with CUDA 12.2** were downloaded from the official NVIDIA site
- Installed using `dpkg -i`
- `CTranslate2` was recompiled to detect and integrate cuDNN automatically

---

## ✅ Final Result

After completing all steps:

- `CTranslate2 v4.4.0` was compiled with **CUDA + cuDNN support**
- `whisperx` runs without errors
- GPU acceleration is enabled (verified with `ctranslate2.get_supported_compute_types("cuda")`)

---

## 🧠 Recommendations

- Freeze GCC versions when using CUDA:

  ```bash
  sudo apt-mark hold gcc-11 g++-11 ...
  ```

- Install `whisperx` with `--no-deps` to avoid version conflicts
- Document compatible versions (CUDA, GCC, cuDNN) in deployment environments

---

## 📎 Useful Resources

- [whisperx](https://github.com/m-bain/whisperx)
- [CTranslate2](https://github.com/OpenNMT/CTranslate2)
- [cuDNN Download](https://developer.nvidia.com/cudnn)
- [CUDA Compatibility Table](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html#system-requirements)
```

