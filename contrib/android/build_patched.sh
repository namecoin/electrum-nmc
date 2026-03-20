#!/bin/bash
# Patched build script for electrum-nmc Android APK
# Applies all fixes for p4a + NDK 19c + QEMU compatibility
set -e

echo "=== Applying patches ==="

# Fix 1: Pin sh<2.0 (sh 2.x breaks p4a's sh.which and stdout handling)
pip3 install --user 'sh>=1.10,<2.0'

# Fix 2: Install lld (p4a checks for it via sh.which)
sudo apt-get update -qq && sudo apt-get install -y -qq lld

# Fix 3: Fix deepcopy pickle error in p4a RecipeOrder
# p4a tries to deepcopy the context which holds os.environ (unpicklable locks)
P4A_GRAPH="/opt/python-for-android/pythonforandroid/graph.py"
if [ -f "$P4A_GRAPH" ]; then
    python3 -c "
import re
with open('$P4A_GRAPH') as f:
    content = f.read()
if '__deepcopy__' not in content:
    # Add __deepcopy__ to RecipeOrder class
    patch = '''
    def __deepcopy__(self, memo):
        cls = self.__class__
        new = cls.__new__(cls)
        memo[id(self)] = new
        import copy
        for k, v in self.__dict__.items():
            if k == 'ctx':
                setattr(new, k, v)  # share ctx by reference
            else:
                setattr(new, k, copy.deepcopy(v, memo))
        return new
'''
    # Insert after the class definition line
    content = content.replace(
        'class RecipeOrder(dict):',
        'class RecipeOrder(dict):' + patch,
        1
    )
    with open('$P4A_GRAPH', 'w') as f:
        f.write(content)
    print('Patched RecipeOrder.__deepcopy__')
else:
    print('RecipeOrder.__deepcopy__ already patched')
"
fi

# Fix 4: Fix 'env must be a mapping' error in p4a build.py
# os.environ gets wrapped; ensure it's cast to dict
P4A_BUILD="/opt/python-for-android/pythonforandroid/build.py"
if [ -f "$P4A_BUILD" ]; then
    sed -i 's/env=copy\.copy(os\.environ)/env=dict(os.environ)/g' "$P4A_BUILD"
    echo "Patched build.py env=dict(os.environ)"
fi

# Fix 5: Limit make parallelism to -j4 (avoid OOM under QEMU emulation)
# p4a hardcodes cpu_count() in archs.py and individual recipes
P4A_ARCHS="/opt/python-for-android/pythonforandroid/archs.py"
if [ -f "$P4A_ARCHS" ]; then
    sed -i "s/cpu_count()/4/g" "$P4A_ARCHS"
    echo "Patched archs.py: cpu_count() -> 4"
fi
# Also patch libsecp256k1 recipe (used by electrum)
P4A_SECP="/opt/python-for-android/pythonforandroid/recipes/libsecp256k1/__init__.py"
if [ -f "$P4A_SECP" ]; then
    sed -i "s/cpu_count()/4/g" "$P4A_SECP"
    echo "Patched libsecp256k1 recipe: cpu_count() -> 4"
fi
export MAKEFLAGS="-j4"

echo "=== Patches applied ==="

# Prepare packages if missing
if [ ! -d "packages" ]; then
    echo "=== Running make_packages ==="
    # make_packages tries to rm packages/ which may not exist
    mkdir -p packages
    python3 -m pip install --no-dependencies --no-binary :all: \
        -r contrib/deterministic-build/requirements.txt -t packages
fi

echo "=== Starting APK build (arm64 only) ==="
export CI=1
exec ./contrib/android/make_apk "$@"
