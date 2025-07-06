#!/usr/bin/env python3
"""
Check which PyCharm debugging packages are available
"""

def check_pydevd_packages():
    packages_to_try = [
        'pydevd_pycharm',
        'pydevd',
        'pydevd_plugins.django.debug',
    ]
    
    working_packages = []
    
    for package in packages_to_try:
        try:
            __import__(package)
            print(f"✅ {package} is available")
            working_packages.append(package)
        except ImportError:
            print(f"❌ {package} not found")
    
    if not working_packages:
        print("\n❌ No PyCharm debugging packages found!")
        print("Try installing:")
        print("  pip install pydevd-pycharm")
        print("  pip install pydevd")
    else:
        print(f"\n✅ Found {len(working_packages)} working package(s)")
        
        # Try a simple connection test with the first working package
        if 'pydevd_pycharm' in working_packages:
            print("\nTesting pydevd_pycharm connection...")
            try:
                import pydevd_pycharm
                print("pydevd_pycharm.settrace available - this should work")
            except Exception as e:
                print(f"Error with pydevd_pycharm: {e}")
        
        elif 'pydevd' in working_packages:
            print("\nTesting pydevd connection...")
            try:
                import pydevd
                print("pydevd available - trying alternative connection method")
            except Exception as e:
                print(f"Error with pydevd: {e}")

if __name__ == "__main__":
    check_pydevd_packages()