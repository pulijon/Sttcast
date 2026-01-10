"""
Parche para permitir cargar modelos de pyannote con PyTorch 2.6+
Agrega globales de omegaconf a los globales seguros de torch y 
deshabilita weights_only en lightning_fabric
"""
import torch
import sys

try:
    # Agregar globales de omegaconf
    from omegaconf import ListConfig, DictConfig
    from omegaconf.base import ContainerMetadata
    from torch.serialization import add_safe_globals
    import typing
    
    add_safe_globals([ListConfig, DictConfig, ContainerMetadata, typing.Any])
    print("✅ PyTorch safe globals patch applied for omegaconf classes")
    
    # Parchar lightning_fabric para usar weights_only=False
    import lightning_fabric.utilities.cloud_io as cloud_io
    _original_load = cloud_io._load
    
    def _load_patched(path_or_url, map_location=None, weights_only=None):
        """Parched version that disables weights_only to avoid issues with pyannote models"""
        return _original_load(path_or_url, map_location=map_location, weights_only=False)
    
    cloud_io._load = _load_patched
    print("✅ Lightning Fabric torch.load patched with weights_only=False")
    
except Exception as e:
    print(f"⚠️  Could not apply PyTorch patch: {e}")
