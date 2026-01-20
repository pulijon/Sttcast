#!/bin/bash

set -e  # Salir si algún comando falla

# Ruta base de trabajo
BASE_DIR="$HOME/tmp/ctranslate2_build"
VERSION="v4.5.0"
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
# Limpiar directorio si existe
if [ -d "CTranslate2" ]; then
  rm -rf CTranslate2
fi

git clone --recursive https://github.com/OpenNMT/CTranslate2.git
cd CTranslate2
git checkout $VERSION

echo "🔧 Aplicando parches para compatibilidad con CMake moderno..."
# Parche para cpu_features CMakeLists.txt
if [ -f "third_party/cpu_features/CMakeLists.txt" ]; then
  sed -i '1s/cmake_minimum_required.*/cmake_minimum_required(VERSION 3.5)/' third_party/cpu_features/CMakeLists.txt
  echo "✅ Parcheado third_party/cpu_features/CMakeLists.txt"
fi

# Parche para el CMakeLists.txt principal si es necesario
if grep -q "cmake_minimum_required.*3\.[0-4]" CMakeLists.txt; then
  sed -i 's/cmake_minimum_required(VERSION 3\.[0-4]/cmake_minimum_required(VERSION 3.5/' CMakeLists.txt
  echo "✅ Parcheado CMakeLists.txt principal"
fi

echo "🔨 Configurando compilación sin Intel OpenMP..."
rm -rf build
mkdir build && cd build

CC=gcc-11 CXX=g++-11 \
cmake -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
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

echo "🔄 Actualizando cache de librerías dinámicas..."
sudo ldconfig

echo "📦 Instalando módulo Python en entorno virtual sin aislamiento..."
cd ../python
pip install . --no-build-isolation

echo "🧪 Verificando instalación..."
python -c "import ctranslate2; print(f'CTranslate2 version: {ctranslate2.__version__}')"
python -c "import ctranslate2; print(f'GPU compute types: {ctranslate2.get_supported_compute_types(\"cuda\")}')"

echo "✅ ¡CTranslate2 instalado correctamente en el entorno virtual!"

