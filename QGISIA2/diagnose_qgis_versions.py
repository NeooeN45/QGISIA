# -*- coding: utf-8 -*-
"""
Script de diagnostic pour les problèmes de versions multiples QGIS
Exécutez ce script pour diagnostiquer et corriger les problèmes
"""
import sys
from pathlib import Path

# Ajouter le dossier du plugin au path
plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

try:
    from version_manager import QgisVersionManager
except ImportError:
    print("ERROR: Impossible d'importer version_manager.py")
    print("Assurez-vous que ce script est dans le même dossier que version_manager.py")
    sys.exit(1)


def print_section(title):
    """Affiche un titre de section"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main():
    """Fonction principale de diagnostic"""
    print_section("Diagnostic des versions multiples QGIS")
    
    manager = QgisVersionManager()
    
    # Informations sur la version actuelle
    print_section("Version actuelle de QGIS")
    current_info = manager.get_qgis_info()
    for key, value in current_info.items():
        print(f"  {key}: {value}")
    
    # Toutes les installations détectées
    print_section("Installations QGIS détectées")
    installations = manager.find_all_qgis_installations()
    
    if not installations:
        print("  Aucune installation supplémentaire détectée")
    else:
        for i, installation in enumerate(installations, 1):
            print(f"\n  Installation {i}:")
            print(f"    Nom: {installation['name']}")
            print(f"    Chemin: {installation['path']}")
            print(f"    Python: {installation['python_dir']}")
            print(f"    Site-packages: {installation['site_packages']}")
    
    # Chemin du plugin
    print_section("Chemin du plugin")
    plugin_path = manager.get_plugin_path()
    print(f"  Plugin path: {plugin_path}")
    print(f"  Existe: {plugin_path.exists()}")
    
    # Conflits détectés
    print_section("Conflits détectés")
    warnings = manager.check_plugin_conflicts()
    
    if not warnings:
        print("  Aucun conflit détecté ✓")
    else:
        print(f"  {len(warnings)} conflit(s) détecté(s):")
        for warning in warnings:
            print(f"    ⚠ {warning}")
    
    # sys.path actuel
    print_section("sys.path (premiers éléments)")
    print("  10 premiers éléments de sys.path:")
    for i, path in enumerate(sys.path[:10], 1):
        print(f"    {i}. {path}")
    
    if len(sys.path) > 10:
        print(f"  ... et {len(sys.path) - 10} autres éléments")
    
    # Recommandations
    print_section("Recommandations")
    
    if warnings:
        print("  Actions recommandées:")
        print("  1. Exécutez: manager.fix_path_issues()")
        print("  2. Vérifiez la variable d'environnement QGIS_PREFIX_PATH")
        print("  3. Assurez-vous que le plugin n'est installé que dans un profil")
    else:
        print("  Aucune action nécessaire ✓")
    
    # Option de réparation automatique
    print_section("Réparation automatique")
    response = input("  Voulez-vous exécuter la réparation automatique ? (y/n): ")
    
    if response.lower() == 'y':
        print("\n  Exécution de la réparation...")
        manager.fix_path_issues()
        print("  Réparation terminée ✓")
        print("\n  Redémarrez QGIS pour appliquer les changements.")
    else:
        print("  Réparation annulée.")
    
    print("\n" + "=" * 60)
    print("Diagnostic terminé")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrompu par l'utilisateur")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
