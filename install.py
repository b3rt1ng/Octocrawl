import os
import sys
import stat
from pathlib import Path

SCRIPT_NAME = "main.py"
COMMAND_NAME = "octocrawl"
SHEBANG = "#!/usr/bin/env python3"

def add_shebang():
    print(f"[*] Checking for shebang in {SCRIPT_NAME}...")
    try:
        with open(SCRIPT_NAME, 'r+') as f:
            content = f.read()
            if not content.startswith(SHEBANG):
                f.seek(0)
                f.write(SHEBANG + '\n' + content)
                print("    -> Shebang added.")
            else:
                print("    -> Shebang already exists.")
    except FileNotFoundError:
        print(f"Error: {SCRIPT_NAME} not found. Make sure you are in the project root directory.")
        sys.exit(1)

def make_executable():
    print(f"[*] Making {SCRIPT_NAME} executable...")
    try:
        st = os.stat(SCRIPT_NAME)
        os.chmod(SCRIPT_NAME, st.st_mode | stat.S_IEXEC)
        print(f"    -> Permissions set to executable.")
    except FileNotFoundError:
        print(f"Error: {SCRIPT_NAME} not found.")
        sys.exit(1)

def setup_symlink():
    source_path = Path.cwd() / SCRIPT_NAME
    target_dir = Path.home() / ".local" / "bin"
    link_path = target_dir / COMMAND_NAME

    print(f"[*] Setting up symbolic link at {link_path}...")
    
    target_dir.mkdir(parents=True, exist_ok=True)

    if link_path.exists():
        link_path.unlink()
    
    link_path.symlink_to(source_path)
    print(f"    -> Symbolic link created for '{COMMAND_NAME}'.")
    return target_dir

def update_shell_config(install_dir):
    print("[*] Checking shell configuration...")
    
    shell = os.getenv("SHELL", "")
    if "zsh" in shell:
        config_file = Path.home() / ".zshrc"
    elif "bash" in shell:
        config_file = Path.home() / ".bashrc"
    else:
        print(f"    -> Unsupported shell ({shell}). Please add '{install_dir}' to your PATH manually.")
        return None

    if not config_file.exists():
        print(f"    -> Config file {config_file} not found. Please add '{install_dir}' to your PATH manually.")
        return None

    path_export_line = f'export PATH="{install_dir}:$PATH"'
    
    with open(config_file, 'r') as f:
        if path_export_line in f.read():
            print(f"    -> Your PATH is already configured in {config_file}.")
            return "no_change"
            
    print(f"    -> Adding PATH configuration to {config_file}...")
    with open(config_file, 'a') as f:
        f.write(f"\n# Added by OctoCrawl installer\n{path_export_line}\n")
    
    return config_file

def main():
    print("🐙 Starting OctoCrawl installation...")

    if os.name != 'posix':
        print("\nError: This installer is designed for Linux and macOS.")
        print("For Windows, please add the script's directory to your system's PATH environment variable manually.")
        sys.exit(1)

    add_shebang()
    make_executable()
    install_dir = setup_symlink()
    config_file_updated = update_shell_config(install_dir)
    
    print("\n" + "="*50)
    print("✅ Installation complete!")
    print("="*50)

    if config_file_updated and config_file_updated != "no_change":
        print("\nIMPORTANT: For the 'octocrawl' command to be available, you must")
        print("either RESTART your terminal, or run the following command:")
        print(f"\n   source {config_file_updated}\n")
    
    print("You can now run the crawler from anywhere by typing:")
    print(f"   {COMMAND_NAME} --help")
    print("="*50 + "\n")


if __name__ == "__main__":
    main()