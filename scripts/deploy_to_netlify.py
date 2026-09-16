import os
import sys
import json
import urllib.request
import urllib.error

def deploy_to_netlify(token: str, site_id: str = None):
    dist_zip = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist", "alibaba_directmail_netlify.zip")
    if not os.path.exists(dist_zip):
        import package_for_netlify
        package_for_netlify.package_netlify_bundle()

    print(f"Deploying {dist_zip} to Netlify...")
    with open(dist_zip, "rb") as f:
        zip_bytes = f.read()

    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/zip"
    }

    if site_id:
        url = f"https://api.netlify.com/api/v1/sites/{site_id}/deploys"
    else:
        url = "https://api.netlify.com/api/v1/sites"

    req = urllib.request.Request(url, data=zip_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            live_url = data.get("ssl_url") or data.get("url")
            admin_url = data.get("admin_url")
            deploy_id = data.get("id")
            site_name = data.get("name")
            print("=" * 65)
            print("🚀 DEPLOYMENT SUCCESSFUL TO NETLIFY!")
            print("=" * 65)
            print(f"Live URL:    {live_url}")
            print(f"Site Name:   {site_name}")
            print(f"Admin Panel: {admin_url}")
            print(f"Deploy ID:   {deploy_id}")
            print("=" * 65)
            return data
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"[ERROR] Netlify API returned HTTP {e.code}: {err_msg}", file=sys.stderr)
        return None

if __name__ == "__main__":
    token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NETLIFY_AUTH_TOKEN")
    if not token:
        print("Usage: python deploy_to_netlify.py <NETLIFY_PERSONAL_ACCESS_TOKEN>")
        sys.exit(1)
    deploy_to_netlify(token)
