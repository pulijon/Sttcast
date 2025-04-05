#!/bin/bash

set -e  # Salir si algún comando falla

# Ruta base de trabajo
BASE_DIR="$HOME/tmp/ctranslate2_build"
VERSION="v4.4.0"
mkdir -p "$BASE_DIR"
cd "$BASE_DIR"

echo "🧱 Instalando dependencias del sistema..."
sudo apt update
sudo apt install -y \
  build-essential \
  cmake \
  g++ \
  python3-dev \
  protobuf-compiler \
  libprotobuf-dev \
  libsentencepiece-dev \
  git

echo "🐍 Asegurando pybind11 en entorno virtual..."
# Verificamos si pybind11 está en el entorno virtual
if ! python -c "import pybind11" &> /dev/null; then
    pip install pybind11
fi

# Obtener el path del módulo CMake de pybind11
PYBIND11_CMAKEDIR=$(python -m pybind11 --cmakedir)
echo "📌 pybind11 CMake dir: $PYBIND11_CMAKEDIR"

echo "📥 Clonando repositorio de CTranslate2 con submódulos..."
git clone --recursive https://github.com/OpenNMT/CTranslate2.git
cd CTranslate2
git checkout $VERSION

echo "🔨 Configurando compilación sin Intel OpenMP..."
rm -rf build
mkdir build && cd build

CC=gcc-11 CXX=g++-11 \
cmake -DCMAKE_BUILD_TYPE=Release \
      -DWITH_PYTHON=ON \
      -DWITH_INTEL_MKL=OFF \
      -DWITH_MKL=OFF \
      -DWITH_OPENMP=ON \
      -DWITH_INTEL_OPENMP=OFF \
      -DOPENMP_RUNTIME=COMP \
      -DWITH_CUDNN=ON \
      -Dpybind11_DIR="$PYBIND11_CMAKEDIR" \
      -DWITH_CUDA=ON \
      -DENABLE_CUDA_FP16=ON \
      ..

echo "⚙ Compilando CTranslate2..."
make -j"$(nproc)"

echo "📂 Instalando CTranslate2 (C++) en el sistema..."
sudo make install

echo "📦 Instalando módulo Python en entorno virtual sin aislamiento..."
cd ../python
pip install . --no-build-isolation

echo "✅ ¡CTranslate2 instalado correctamente en el entorno virtual!"

