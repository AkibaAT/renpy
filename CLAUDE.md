# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Ren'Py Visual Novel Engine** - a comprehensive game development framework for creating visual novels, interactive fiction, and story-based games. The project is written primarily in Python with performance-critical components implemented in Cython and C.

## Key Architecture

### Core Components

- **renpy/**: Main engine code organized into modules
  - `display/`: Graphics rendering, displayables, transforms, transitions
  - `audio/`: Sound system, music, audio filters
  - `text/`: Text rendering, fonts, internationalization
  - `gl2/`: OpenGL 2.0+ rendering pipeline, 3D graphics, Live2D support
  - `styledata/`: Style system for UI theming
  - `testing/`: Automated testing framework with HTTP API
  - `translation/`: Internationalization and localization system

- **launcher/**: Game launcher and development environment
- **gui/**: Default GUI templates and assets
- **tutorial/**: Interactive tutorial game
- **sphinx/**: Documentation generation system
- **src/**: C/C++ source code for performance-critical modules

### Build System

The project uses a Docker-based build system for cross-platform compilation:
- **docker-compose.yml**: Docker Compose configuration using `ghcr.io/akibaat/renpy-build:docker`
- **build.py**: Main build script (located in Docker container at `/build/build.py`)
- **setup.py**: Python package setup script for manual builds
- **scripts/setuplib.py**: Build utilities and configuration
- **pyproject.toml**: Python project configuration with type checker settings

#### Docker Build Architecture
- Uses separate `renpy-build` repository for build toolchain
- Supports multiple platforms: linux, windows, mac, android, ios, web
- Supports multiple architectures: x86_64, aarch64, arm64_v8a, armeabi_v7a, arm64, sim-x86_64, sim-arm64, wasm
- Mounted volumes for source code and build cache persistence

### Game Structure

Ren'Py games are organized as:
- **game/**: Game scripts (.rpy files), assets, and configuration
- **common/**: Shared engine code available to all games
- **lib/**: Platform-specific compiled modules and dependencies

## Common Development Commands

### Running Ren'Py
```bash
# Run a game (Linux/Mac)
./renpy.sh path/to/game

# Run with Python 3
./renpy3.sh path/to/game

# Run the launcher
./renpy.sh launcher

# Run in headless mode (for testing)
./renpy.sh mygame --headless
```

### Building from Source

#### Docker Build (Recommended)
```bash
# Build for Linux x86_64 (most common)
docker compose run --rm builder ./build.py --platform linux --arch x86_64

# Build for other platforms
docker compose run --rm builder ./build.py --platform windows --arch x86_64
docker compose run --rm builder ./build.py --platform mac --arch arm64
docker compose run --rm builder ./build.py --platform android --arch arm64_v8a

# Clean build cache
docker compose run --rm builder ./build.py --clean

# Rebuild (clean + build)
docker compose run --rm builder ./build.py --rebuild --platform linux --arch x86_64
```

#### Manual Build (Alternative)
```bash
# Install dependencies (Ubuntu/Debian)
sudo apt install virtualenvwrapper python3-dev libassimp-dev libavcodec-dev libavformat-dev \
    libswresample-dev libswscale-dev libharfbuzz-dev libfreetype6-dev libfribidi-dev libsdl2-dev \
    libsdl2-image-dev libsdl2-gfx-dev libsdl2-mixer-dev libsdl2-ttf-dev libjpeg-dev pkg-config

# Create virtual environment
mkvirtualenv renpy
pip install -U setuptools cython future six typing pefile requests ecdsa

# Build pygame_sdl2 dependency
git clone https://www.github.com/renpy/pygame_sdl2
cd pygame_sdl2
python setup.py install
cd ..

# Build Ren'Py modules
python setup.py install

# Run from source
python renpy.py
```

### Documentation
```bash
# Build documentation (requires Sphinx)
cd sphinx
./build.sh

# Install Sphinx dependencies
pip install -U sphinx sphinx_rtd_theme sphinx_rtd_dark_mode
```

### Testing
```bash
# Run unit tests
python -m pytest renpy/test/

# Run experimental tests
cd experimental/cslots
./test.sh

# Start HTTP testing server
./renpy.sh mygame http_server --port 8080

# Run automated tests
./renpy.sh mygame autotest --headless
```

### Development Setup

#### Docker Development (Recommended)
```bash
# Build current development version
docker compose run --rm builder ./build.py --platform linux --arch x86_64

# Interactive development shell
docker compose run --rm builder bash

# Clean and rebuild for development
docker compose run --rm builder ./build.py --clean --rebuild --platform linux --arch x86_64
```

#### Manual Development Setup
```bash
# After checking out, link to nightly build
./after_checkout.sh path/to/nightly

# Build modules for development
python setup.py clean --all
python setup.py install_lib -d $PYTHONPATH
```

## Branch Structure

- **fix**: Stable fixes and documentation updates (targets renpy.org docs)
- **master**: Main development branch for new features
- **docker**: Docker-related development (current branch)

## Key Files for Development

- **renpy.py**: Main entry point
- **renpy/__init__.py**: Engine initialization
- **renpy/main.py**: Game execution and launcher logic
- **renpy/config.py**: Configuration system
- **renpy/game.py**: Game state management
- **renpy/script.py**: Script parsing and execution
- **renpy/display/core.py**: Core display system
- **renpy/audio/audio.py**: Audio system
- **renpy/text/text.py**: Text rendering

## Live2D Support

The project includes Live2D Cubism SDK support:
- Set `CUBISM` environment variable to SDK path before building
- Live2D models are handled in `renpy/gl2/live2d.py`
- Requires commercial Live2D license for distribution

## Type Checking

The project uses Pyright/Cyright for type checking:
- Configuration in `pyproject.toml`
- Many optional checks disabled due to dynamic nature of the engine
- Type stubs available in `scripts/pyi/`

## Testing Framework

Comprehensive automated testing system:
- HTTP API server for external test control
- Python API for programmatic testing
- State inspection and manipulation
- Headless mode for CI/CD environments
- See `renpy/testing/README.md` for full documentation

## Platform Support

- Linux (x86_64, ARM)
- Windows (x86_64, x86)
- macOS (Universal Binary)
- Android (via special build process)
- iOS (via special build process)
- Web (Emscripten, experimental)

## Security Notes

- Never commit secrets or API keys
- Testing HTTP API is for development only
- Disable testing endpoints in production builds
- Use proper sandboxing for user-generated content