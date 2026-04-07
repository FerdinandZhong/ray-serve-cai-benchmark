#!/bin/bash
set -e

echo "=============================================================="
echo "Starting ray-serve-cai-bench environment setup (with uv)"
echo "=============================================================="

# Sync latest code from repository
echo "Syncing latest code from repository..."
cd /home/cdsw
if [ -d ".git" ]; then
    if git pull; then
        echo "Code synced successfully"
    else
        echo "Git pull failed (continuing with existing code)"
    fi
else
    echo "Not a git repository, skipping git sync"
fi

VENV_PATH="/home/cdsw/.venv"

# Check if we can skip setup (venv exists with required packages installed)
check_existing_setup() {
    if [ -d "$VENV_PATH" ] && [ -f "$VENV_PATH/bin/python" ]; then
        if "$VENV_PATH/bin/python" -c "import locust; import httpx; import dotenv; import yaml" 2>/dev/null; then
            echo "  (benchmark environment detected)"
            return 0
        fi
    fi
    return 1
}

# Check FORCE_REINSTALL flag
if [ "${FORCE_REINSTALL:-false}" = "true" ]; then
    echo "FORCE_REINSTALL=true, performing full setup..."
    SKIP_SETUP=false
elif check_existing_setup; then
    echo "Existing setup detected with required packages installed"
    SKIP_SETUP=true
else
    echo "No existing setup found, performing full setup..."
    SKIP_SETUP=false
fi

if [ "$SKIP_SETUP" = "true" ]; then
    echo "Skipping environment setup (use FORCE_REINSTALL=true to force)"

    # Verify the installation
    echo "Verifying installation..."
    source "$VENV_PATH/bin/activate"
    python -c "import locust; import httpx; print(f'Locust: {locust.__version__}, httpx: {httpx.__version__}')"

    echo "=============================================================="
    echo "Environment already configured - setup skipped"
    echo "Virtual environment location: $VENV_PATH"
    echo "=============================================================="
else
    # Full setup path
    if [ -d "$VENV_PATH" ]; then
        if [ "${FORCE_REINSTALL:-false}" = "true" ]; then
            echo "Removing existing virtual environment for reinstall..."
            rm -rf "$VENV_PATH"
            echo "Creating new virtual environment at $VENV_PATH"
            python3.11 -m venv "$VENV_PATH" || python3 -m venv "$VENV_PATH"
            echo "Virtual environment created successfully"
        else
            echo "Virtual environment already exists at $VENV_PATH"
            echo "  Reusing existing environment..."
        fi
    else
        echo "Creating new virtual environment at $VENV_PATH"
        python3.11 -m venv "$VENV_PATH" || python3 -m venv "$VENV_PATH"
        echo "Virtual environment created successfully"
    fi

    # Activate virtual environment
    echo "Activating virtual environment..."
    source "$VENV_PATH/bin/activate"

    # Disable --user flag (conflicts with virtualenv)
    export PIP_USER=0

    # Install uv if not already installed
    echo "Installing uv (ultra-fast Python package installer)..."
    if ! command -v uv &> /dev/null; then
        echo "uv not found, installing..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
        echo "uv installed successfully"
    else
        echo "uv already installed"
    fi

    # Verify uv is available
    if ! command -v uv &> /dev/null; then
        echo "uv installation failed, falling back to pip..."
        USE_UV=false
    else
        echo "Using uv version: $(uv --version)"
        USE_UV=true
    fi

    # Determine requirements file
    if [ -n "${REQUIREMENTS_FILE:-}" ] && [ -f "$REQUIREMENTS_FILE" ]; then
        echo "Using requirements file from REQUIREMENTS_FILE env var: $REQUIREMENTS_FILE"
    elif [ -f "pyproject.toml" ]; then
        # Install from pyproject.toml (editable)
        REQUIREMENTS_FILE=""
        echo "Installing from pyproject.toml..."
    else
        echo "Error: No requirements file or pyproject.toml found"
        exit 1
    fi

    if [ "$USE_UV" = "true" ]; then
        echo "Using uv for ultra-fast installation..."

        # Clear stale locks
        if [ -d "$HOME/.cache/uv" ]; then
            find "$HOME/.cache/uv" -name "*.lock" -type f -delete 2>/dev/null || true
        fi

        MAX_RETRIES=3
        RETRY_COUNT=0

        while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
            if [ -n "$REQUIREMENTS_FILE" ]; then
                INSTALL_CMD="uv pip install -r $REQUIREMENTS_FILE"
            else
                INSTALL_CMD="uv pip install -e ."
            fi

            if $INSTALL_CMD; then
                echo "All dependencies installed successfully"
                break
            else
                RETRY_COUNT=$((RETRY_COUNT + 1))
                if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
                    echo "Installation failed, retrying ($RETRY_COUNT/$MAX_RETRIES)..."
                    rm -rf "$HOME/.cache/uv/sdists-v9" 2>/dev/null || true
                    sleep 5
                else
                    echo "uv installation failed after $MAX_RETRIES attempts"
                    echo "Falling back to pip..."
                    pip install --upgrade pip
                    if [ -n "$REQUIREMENTS_FILE" ]; then
                        pip install -r "$REQUIREMENTS_FILE"
                    else
                        pip install -e .
                    fi
                    echo "All dependencies installed successfully (via pip fallback)"
                fi
            fi
        done
    else
        echo "Using pip..."
        pip install --upgrade pip
        if [ -n "$REQUIREMENTS_FILE" ]; then
            pip install -r "$REQUIREMENTS_FILE"
        else
            pip install -e .
        fi
        echo "All dependencies installed successfully"
    fi

    # Verify installation
    echo "Verifying installation..."
    python -c "
import locust
import httpx
import yaml
import dotenv
import matplotlib
print(f'Locust: {locust.__version__}')
print(f'httpx: {httpx.__version__}')
print(f'PyYAML: {yaml.__version__}')
print(f'python-dotenv: {dotenv.__version__}')
print(f'matplotlib: {matplotlib.__version__}')
print('All benchmark dependencies verified')
"

    echo "=============================================================="
    echo "Environment setup completed successfully!"
    if [ "$USE_UV" = "true" ]; then
        echo "Installed using uv (10-100x faster than pip)"
    fi
    echo "Virtual environment location: $VENV_PATH"
    echo "=============================================================="
fi
