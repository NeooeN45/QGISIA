# -*- coding: utf-8 -*-
"""
Détection des capacités du système pour Ollama et LLM
"""
import platform
import subprocess
import os
from typing import Dict, List, Optional

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _psutil = None  # type: ignore
    _HAS_PSUTIL = False


def _ram_total_gb_fallback() -> float:
    """Fallback RAM total via ctypes (Windows) ou /proc/meminfo (Linux/Mac)"""
    try:
        if platform.system() == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return (round(stat.ullTotalPhys / (1024**3), 1),
                    round(stat.ullAvailPhys / (1024**3), 1))
        elif os.path.exists("/proc/meminfo"):
            total, avail = 0, 0
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1]) * 1024
                    elif line.startswith("MemAvailable:"):
                        avail = int(line.split()[1]) * 1024
            return (round(total / (1024**3), 1), round(avail / (1024**3), 1))
    except Exception:
        pass
    return (8.0, 4.0)


def _cpu_count_fallback():
    """Fallback CPU count via os.cpu_count"""
    try:
        logical = os.cpu_count() or 1
        return logical, max(1, logical // 2)
    except Exception:
        return 1, 1


class SystemCapabilities:
    """Détecte les capacités du système pour recommander des LLM"""
    
    def __init__(self):
        self.system_info = self._get_system_info()
    
    def _get_system_info(self) -> Dict:
        """Récupère les informations du système"""
        if _HAS_PSUTIL:
            ram_total = round(_psutil.virtual_memory().total / (1024**3), 1)
            ram_avail = round(_psutil.virtual_memory().available / (1024**3), 1)
            cpu_logical = _psutil.cpu_count(logical=True) or 1
            cpu_physical = _psutil.cpu_count(logical=False) or 1
        else:
            ram_total, ram_avail = _ram_total_gb_fallback()
            cpu_logical, cpu_physical = _cpu_count_fallback()

        info = {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "ram_total_gb": ram_total,
            "ram_available_gb": ram_avail,
            "cpu_count": cpu_logical,
            "cpu_physical_count": cpu_physical,
        }
        
        # Détection GPU
        info["gpu"] = self._detect_gpu()
        
        return info
    
    def _detect_gpu(self) -> Dict:
        """Détecte la présence et les capacités du GPU"""
        gpu_info = {
            "has_gpu": False,
            "gpu_name": None,
            "gpu_memory_gb": None,
            "supports_cuda": False,
            "supports_rocm": False,
        }
        
        try:
            # Tentative de détection NVIDIA avec nvidia-smi
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                gpu_info["has_gpu"] = True
                gpu_info["supports_cuda"] = True
                lines = result.stdout.strip().split("\n")
                if lines:
                    parts = lines[0].split(", ")
                    gpu_info["gpu_name"] = parts[0].strip()
                    if len(parts) > 1:
                        mem_str = parts[1].strip()
                        # Extraire la valeur en GB
                        mem_gb = float(mem_str.split()[0])
                        gpu_info["gpu_memory_gb"] = mem_gb
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass
        
        return gpu_info
    
    def get_ollama_recommendation(self) -> Dict:
        """Recommande les modèles Ollama adaptés au système"""
        ram_gb = self.system_info["ram_total_gb"]
        has_gpu = self.system_info["gpu"]["has_gpu"]
        gpu_memory_gb = self.system_info["gpu"]["gpu_memory_gb"]
        
        recommendations = {
            "can_run_local": False,
            "recommended_models": [],
            "max_model_size_gb": 0,
            "reason": "",
        }
        
        # Calculer la mémoire disponible pour les modèles
        # On réserve 4GB pour le système + Ollama
        available_for_models = max(0, ram_gb - 4)
        
        if available_for_models < 4:
            recommendations["reason"] = "RAM insuffisante pour exécuter des LLM locaux"
            return recommendations
        
        recommendations["can_run_local"] = True
        recommendations["max_model_size_gb"] = available_for_models
        
        # Recommandations basées sur la RAM et le GPU (2025 - Modèles récents)
        if has_gpu and gpu_memory_gb:
            # Avec GPU
            if gpu_memory_gb >= 16:
                recommendations["recommended_models"] = [
                    {"name": "gemma4:27b", "size_gb": 18, "description": "Google Gemma 4 27B — meilleur rapport qualité/taille 2025", "recommended": True},
                    {"name": "qwen3:30b-a3b", "size_gb": 19, "description": "Qwen3 30B MoE — qualité maximale avec MoE efficace"},
                    {"name": "llama3.3:70b", "size_gb": 45, "description": "Llama 3.3 70B — modèle très puissant"},
                    {"name": "qwen3:8b", "size_gb": 5.2, "description": "Qwen3 8B — rapide et multilingue"},
                ]
                recommendations["reason"] = "GPU puissant détecté (16GB+), modèles 2025 haute qualité recommandés"
            elif gpu_memory_gb >= 8:
                recommendations["recommended_models"] = [
                    {"name": "gemma4:12b", "size_gb": 9, "description": "Google Gemma 4 12B — multimodal et puissant", "recommended": True},
                    {"name": "qwen3:8b", "size_gb": 5.2, "description": "Qwen3 8B — très bon suivi d'instructions", "recommended": False},
                    {"name": "llama3.3:8b", "size_gb": 4.9, "description": "Llama 3.3 8B — excellent équilibre"},
                    {"name": "mistral:7b", "size_gb": 4.5, "description": "Mistral 7B — rapide et performant"},
                ]
                recommendations["reason"] = "GPU moyen détecté (8GB), modèles 2025 qualité moyenne recommandés"
            elif gpu_memory_gb >= 4:
                recommendations["recommended_models"] = [
                    {"name": "gemma4:4b", "size_gb": 3.3, "description": "Google Gemma 4 4B — excellent rapport qualité/taille", "recommended": True},
                    {"name": "qwen3:4b", "size_gb": 2.8, "description": "Qwen3 4B — compact et performant"},
                    {"name": "llama3.2:3b", "size_gb": 2.0, "description": "Llama 3.2 3B — ultra rapide"},
                    {"name": "phi4:3b", "size_gb": 2.2, "description": "Phi-4 3B — Microsoft compact"},
                ]
                recommendations["reason"] = "GPU avec mémoire limitée (4GB), modèles compacts 2025 recommandés"
            else:
                recommendations["recommended_models"] = [
                    {"name": "gemma4:2b", "size_gb": 1.7, "description": "Google Gemma 4 2B — ultra léger", "recommended": True},
                    {"name": "llama3.2:1b", "size_gb": 1.3, "description": "Llama 3.2 1B — le plus rapide"},
                    {"name": "smollm2:1.7b", "size_gb": 1.1, "description": "SmolLM2 1.7B — ultra compact"},
                ]
                recommendations["reason"] = "GPU faible, modèles ultra compacts recommandés"
        else:
            # Sans GPU (CPU only)
            if available_for_models >= 16:
                recommendations["recommended_models"] = [
                    {"name": "gemma4:9b", "size_gb": 6.5, "description": "Google Gemma 4 9B — optimisé CPU", "recommended": True},
                    {"name": "qwen3:8b", "size_gb": 5.2, "description": "Qwen3 8B — bon sur CPU"},
                    {"name": "llama3.3:8b", "size_gb": 4.9, "description": "Llama 3.3 8B — CPU optimisé"},
                    {"name": "mistral:7b", "size_gb": 4.5, "description": "Mistral 7B — rapide"},
                ]
                recommendations["reason"] = "CPU uniquement (16GB+ RAM), modèles 2025 optimisés CPU recommandés"
            elif available_for_models >= 8:
                recommendations["recommended_models"] = [
                    {"name": "gemma4:4b", "size_gb": 3.3, "description": "Google Gemma 4 4B — ultra compact", "recommended": True},
                    {"name": "qwen3:4b", "size_gb": 2.8, "description": "Qwen3 4B — rapide sur CPU"},
                    {"name": "llama3.2:3b", "size_gb": 2.0, "description": "Llama 3.2 3B — léger"},
                ]
                recommendations["reason"] = "RAM limitée (8GB), modèles compacts 2025 recommandés"
            elif available_for_models >= 4:
                recommendations["recommended_models"] = [
                    {"name": "gemma4:2b", "size_gb": 1.7, "description": "Google Gemma 4 2B — ultra léger", "recommended": True},
                    {"name": "llama3.2:1b", "size_gb": 1.3, "description": "Llama 3.2 1B — rapide"},
                    {"name": "smollm2:1.7b", "size_gb": 1.1, "description": "SmolLM2 1.7B — très compact"},
                ]
                recommendations["reason"] = "RAM minimale (4-8GB), modèles ultra compacts recommandés"
            else:
                recommendations["recommended_models"] = [
                    {"name": "smollm2:360m", "size_gb": 0.6, "description": "SmolLM2 360M — le plus petit", "recommended": True},
                ]
                recommendations["reason"] = "RAM très limitée, seul modèle minimal possible"
        
        return recommendations
    
    def get_all_available_models(self) -> List[Dict]:
        """Retourne la liste de tous les modèles Ollama disponibles (2025)"""
        models = [
            # Modèles très puissants 2025 (16GB+ GPU)
            {"name": "gemma4:27b", "size_gb": 18, "category": "high", "description": "Google Gemma 4 27B — meilleur rapport 2025", "requires_gpu": True, "min_ram_gb": 24},
            {"name": "qwen3:30b-a3b", "size_gb": 19, "category": "high", "description": "Qwen3 30B MoE — qualité maximale", "requires_gpu": True, "min_ram_gb": 24},
            {"name": "llama3.3:70b", "size_gb": 45, "category": "high", "description": "Llama 3.3 70B — très puissant", "requires_gpu": True, "min_ram_gb": 48},
            {"name": "deepseek-v3:8b", "size_gb": 6, "category": "high", "description": "DeepSeek V3 distillé", "requires_gpu": True, "min_ram_gb": 10},
            
            # Modèles puissants 2025 (8GB+ GPU / 16GB RAM)
            {"name": "gemma4:12b", "size_gb": 9, "category": "medium", "description": "Google Gemma 4 12B — multimodal", "requires_gpu": False, "min_ram_gb": 12},
            {"name": "qwen3:8b", "size_gb": 5.2, "category": "medium", "description": "Qwen3 8B — excellent suivi instructions", "requires_gpu": False, "min_ram_gb": 8},
            {"name": "llama3.3:8b", "size_gb": 4.9, "category": "medium", "description": "Llama 3.3 8B — équilibre parfait", "requires_gpu": False, "min_ram_gb": 8},
            {"name": "mistral:7b", "size_gb": 4.5, "category": "medium", "description": "Mistral 7B — rapide et performant", "requires_gpu": False, "min_ram_gb": 8},
            {"name": "gemma4:9b", "size_gb": 6.5, "category": "medium", "description": "Google Gemma 4 9B — CPU optimisé", "requires_gpu": False, "min_ram_gb": 10},
            
            # Modèles compacts 2025 (4-8GB RAM)
            {"name": "gemma4:4b", "size_gb": 3.3, "category": "low", "description": "Google Gemma 4 4B — ultra efficace", "requires_gpu": False, "min_ram_gb": 6},
            {"name": "qwen3:4b", "size_gb": 2.8, "category": "low", "description": "Qwen3 4B — compact multilingue", "requires_gpu": False, "min_ram_gb": 5},
            {"name": "llama3.2:3b", "size_gb": 2.0, "category": "low", "description": "Llama 3.2 3B — ultra rapide", "requires_gpu": False, "min_ram_gb": 4},
            {"name": "phi4:3b", "size_gb": 2.2, "category": "low", "description": "Phi-4 3B — Microsoft", "requires_gpu": False, "min_ram_gb": 4},
            
            # Modèles ultra compacts 2025 (2-4GB RAM)
            {"name": "gemma4:2b", "size_gb": 1.7, "category": "minimal", "description": "Google Gemma 4 2B — ultra léger", "requires_gpu": False, "min_ram_gb": 3},
            {"name": "llama3.2:1b", "size_gb": 1.3, "category": "minimal", "description": "Llama 3.2 1B — le plus rapide", "requires_gpu": False, "min_ram_gb": 3},
            {"name": "smollm2:1.7b", "size_gb": 1.1, "category": "minimal", "description": "SmolLM2 1.7B — très compact", "requires_gpu": False, "min_ram_gb": 3},
            {"name": "smollm2:360m", "size_gb": 0.6, "category": "minimal", "description": "SmolLM2 360M — minimal", "requires_gpu": False, "min_ram_gb": 2},
            
            # Anciens modèles (rétrocompatibilité)
            {"name": "llama3.1:8b", "size_gb": 4.5, "category": "legacy", "description": "Llama 3.1 8B (legacy)", "requires_gpu": False, "min_ram_gb": 8},
            {"name": "qwen2.5:7b", "size_gb": 4.5, "category": "legacy", "description": "Qwen2.5 7B (legacy)", "requires_gpu": False, "min_ram_gb": 6},
        ]
        
        # Filtrer selon les capacités du système
        available_models = []
        for model in models:
            if self.system_info["ram_total_gb"] >= model["min_ram_gb"]:
                if not model["requires_gpu"] or self.system_info["gpu"]["has_gpu"]:
                    available_models.append(model)
        
        return available_models
    
    def to_dict(self) -> Dict:
        """Retourne toutes les informations sous forme de dictionnaire"""
        return {
            "system_info": self.system_info,
            "recommendations": self.get_ollama_recommendation(),
            "available_models": self.get_all_available_models(),
        }


# Instance globale
system_capabilities = SystemCapabilities()
