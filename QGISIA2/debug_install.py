# -*- coding: utf-8 -*-
r"""
Script de debug pour l'installation Gateway IA.
À exécuter dans la console Python de QGIS:

    exec(open(r'C:\Users\camil\AppData\Roaming\QGIS\QGIS4\profiles\default\python\plugins\QGISIA2\debug_install.py').read())
"""
import sys
import os

# Détection du chemin du plugin
plugin_dir = os.path.dirname(__file__)
print(f"=" * 60)
print(f"🔧 DEBUG INSTALLATION GATEWAY IA")
print(f"=" * 60)
print(f"\n📁 Plugin dir: {plugin_dir}")

# Ajout au path
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)
    print(f"✅ Plugin ajouté au sys.path")

# Test import
print(f"\n📦 Test imports...")
try:
    import llm_installer
    print(f"✅ llm_installer importé")
    print(f"   VENDOR_DIR: {llm_installer.VENDOR_DIR}")
    print(f"   MARKER_FILE: {llm_installer.MARKER_FILE}")
    print(f"   Vendor exists: {llm_installer.VENDOR_DIR.exists()}")
    print(f"   Vendor ready: {llm_installer.is_vendor_ready()}")
except Exception as e:
    print(f"❌ Erreur import llm_installer: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test pip
print(f"\n🐍 Test pip...")
import subprocess
try:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True,
        text=True,
        timeout=10
    )
    print(f"   Exit code: {result.returncode}")
    print(f"   stdout: {result.stdout.strip()}")
    if result.stderr:
        print(f"   stderr: {result.stderr.strip()}")
except Exception as e:
    print(f"❌ Erreur pip: {e}")

# Lancement installation
print(f"\n🚀 Lancement installation...")
print(f"   Cela peut prendre 30-60s...")
print(f"   Appuyez sur Ctrl+C pour annuler")
print(f"-" * 60)

try:
    def progress(msg):
        print(f"   📍 {msg}")
    
    result = llm_installer.install_if_needed(progress_cb=progress, force=True)
    
    print(f"\n" + "=" * 60)
    print(f"📊 RÉSULTAT")
    print(f"=" * 60)
    print(f"   Success: {result.get('success')}")
    print(f"   Already installed: {result.get('already_installed')}")
    if result.get('error'):
        print(f"   ❌ Error: {result.get('error')}")
    
    print(f"\n📋 LOGS:")
    for log in result.get('logs', []):
        level = log.get('level', 'info')
        stage = log.get('stage', '?')
        msg = log.get('message', '')
        icon = "✅" if level == "info" else "⚠️" if level == "warning" else "❌"
        print(f"   {icon} [{stage}] {msg}")
    
    # Vérification finale
    print(f"\n🔍 Vérification finale:")
    print(f"   Vendor ready: {llm_installer.is_vendor_ready()}")
    
except KeyboardInterrupt:
    print(f"\n\n⚠️ Interrompu par l'utilisateur")
except Exception as e:
    print(f"\n❌ Exception: {e}")
    import traceback
    traceback.print_exc()

print(f"\n" + "=" * 60)
print(f"✅ Debug terminé")
print(f"=" * 60)
