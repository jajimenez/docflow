#!/bin/bash

# Exit on error
set -e

# User's Bash configuration
bashrc_file="$HOME/.bashrc"

# Secrets file (it will be created if it doesn't exist and it must never be committed
# to version control systems).
secrets_env_file=/workspace/docflow/.devcontainer/secrets.env

# Initialize Docflow
echo "Initializing Docflow..."

# Install the project in editable mode with its dependencies into Airflow's
# own Python environment. This serves double duty: Airflow can import from
# the docflow package at DAG runtime, and VS Code uses the same environment.
echo "Installing Docflow..."
pip install -e "/workspace/docflow[dev]"

# Generate Airflow secrets only if they don't exist yet. The FERNET_KEY in
# particular must remain stable for the lifetime of the metadata database —
# regenerating it would make all previously encrypted data permanently unreadable.
if [ ! -f "$secrets_env_file" ]; then
    echo "Generating Airflow secrets..."

    # Signs JWT tokens for the Airflow REST API and web UI sessions.
    # If this changes, active sessions are invalidated (users are logged out), but no data is lost.
    API_SECRET="$(openssl rand -base64 32)"

    # Encrypts sensitive data stored in the metadata database (connection passwords, variable values).
    # If this changes, all previously encrypted data becomes permanently unreadable, so it must
    # remain stable for the lifetime of the metadata database.
    FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

    echo "AIRFLOW__API__SECRET_KEY=$API_SECRET" > "$secrets_env_file"
    echo "AIRFLOW__CORE__FERNET_KEY=$FERNET_KEY" >> "$secrets_env_file"
fi

# Export variables for the current session
set -a
. "$secrets_env_file"
set +a

# Update the Bash configuration to export the environment variables in future sessions
if ! grep -q "Docflow environment variables" "$bashrc_file"; then
    echo "Updating Bashrc file..."

    {
        echo ""
        echo "# Docflow environment variables"
        echo "set -a"
        echo ". \"$secrets_env_file\""
        echo "set +a"
    } >> "$bashrc_file"
fi

# Initialize the Airflow database
echo "Initializing Airflow metadata database..."
airflow db migrate

# Seed the SimpleAuthManager password file with a known development password.
# Airflow 3 uses SimpleAuthManager by default; it stores passwords in
# plaintext JSON (by design for development — do not use this in production).
# Storing the file in the workspace means the password survives rebuilds.
echo "Creating Airflow admin user..."
echo '{"admin":"admin"}' > /workspace/docflow/.devcontainer/airflow-passwords.json

echo "Docflow initialization completed."
