import os
import zipfile
import shutil

def package_netlify_bundle():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_dir = os.path.join(base_dir, "frontend")
    dist_dir = os.path.join(base_dir, "dist")
    downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(dist_dir, exist_ok=True)
    
    zip_paths = [
        os.path.join(dist_dir, "alibaba_directmail_netlify.zip"),
        os.path.join(downloads_dir, "alibaba_directmail_netlify.zip")
    ]
    
    for zip_path in zip_paths:
        print(f"Creating Netlify bundle -> {zip_path}")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            toml_path = os.path.join(base_dir, "netlify.toml")
            if os.path.exists(toml_path):
                z.write(toml_path, "netlify.toml")
            for root, dirs, files in os.walk(frontend_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, frontend_dir)
                    z.write(file_path, rel_path)
                    if not rel_path.startswith("static"):
                        z.write(file_path, os.path.join("static", rel_path))
        print(f"  [OK] Size: {os.path.getsize(zip_path)/1024:.1f} KB")

    # Also build full project zip to Downloads
    full_zip = os.path.join(downloads_dir, "alibaba_email_agent_full_project.zip")
    with zipfile.ZipFile(full_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(base_dir):
            if "__pycache__" in root or ".git" in root or "dist" in root:
                continue
            for f in files:
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, base_dir)
                z.write(full, rel)
    print(f"  [OK] Full Project Size: {os.path.getsize(full_zip)/1024:.1f} KB")

if __name__ == "__main__":
    package_netlify_bundle()
