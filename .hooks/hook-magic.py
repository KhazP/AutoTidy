from PyInstaller.utils.hooks import collect_dynamic_libs

# Collect dynamic libraries for python-magic
binaries = collect_dynamic_libs('magic') 