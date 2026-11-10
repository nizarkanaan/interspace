"""Build a local ad-hoc signed Mac app. No network or project-data embedding."""
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
if sys.platform != 'darwin':
    raise SystemExit('The native app build requires macOS and Xcode command-line tools.')
app = root / 'dist/Interspace.app'
contents = app / 'Contents'
resources = contents / 'Resources'
(contents / 'MacOS').mkdir(parents=True, exist_ok=True)
resources.mkdir(parents=True, exist_ok=True)
for relative in ['app/backend', 'app/ui', 'pilot']:
    destination = resources / relative
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(root / relative, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for relative in ['design/scene/lab-scene.js','design/agents/role-catalog.js','design/agents/role-contracts.json']:
    destination = resources / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / relative, destination)
# UI references scene assets within its own permitted read directory.
shutil.copy2(root / 'design/scene/lab-scene.js', resources / 'app/ui/lab-scene.js')
with (contents / 'Info.plist').open('wb') as f:
    plistlib.dump({'CFBundleExecutable':'Interspace','CFBundleIdentifier':'local.interspace.desktop',
                  'CFBundleName':'Interspace','CFBundleDisplayName':'Interspace','CFBundlePackageType':'APPL',
                  'CFBundleShortVersionString':'0.1.0','CFBundleVersion':'1','LSMinimumSystemVersion':'13.0',
                  'NSHighResolutionCapable':True,'NSHumanReadableCopyright':'Interspace local development build'},f)
cache = root / 'workspace-data/swift-module-cache'
cache.mkdir(parents=True, exist_ok=True)
subprocess.run(['swiftc','-swift-version','5','-target','arm64-apple-macos13.0','-O','-module-cache-path',str(cache),
                '-framework','AppKit','-framework','WebKit',str(root/'app/macos/main.swift'),
                '-o',str(contents/'MacOS/Interspace')],check=True)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app)
