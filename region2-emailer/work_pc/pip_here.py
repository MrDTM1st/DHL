"""
pip, through the corporate proxy, with the corporate CA. One command.

    python pip_here.py                 installs requirements.txt
    python pip_here.py <pkg> [pkg...]  installs named packages instead

Two separate walls sit between a managed machine and pypi.org, and they fail
one after the other, which makes it feel like nothing is working:

  1. The proxy. The browser reads the PAC file automatically; pip cannot read
     a PAC at all, so it goes direct and gets "WinError 10061 ... actively
     refused". This reads the PAC and pulls the proxy out of it.
  2. TLS inspection. Once pip reaches pypi through the proxy, the certificate
     it is shown is the corporate one, not pypi's, so it fails with
     CERTIFICATE_VERIFY_FAILED. The usual advice is --trusted-host, which
     just turns certificate checking off. Instead this exports the machine's
     OWN trusted-root store - which already contains the corporate CA, or the
     browser would be showing warnings too - into a PEM bundle and hands that
     to pip with --cert. Verification stays ON, against the right roots.

Standard library only, so it runs before anything is installed.
"""
import base64
import os
import re
import ssl
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
BUNDLE = os.path.join(HERE, "_win_ca_bundle.pem")


def proxy_from_pac():
    """The proxy pip should use, read out of the system PAC file."""
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            try:
                explicit = winreg.QueryValueEx(k, "ProxyServer")[0]
            except OSError:
                explicit = None
            try:
                pac = winreg.QueryValueEx(k, "AutoConfigURL")[0]
            except OSError:
                pac = None
    except Exception as e:
        print(f"  could not read proxy settings: {type(e).__name__}: {e}")
        return None
    if explicit:
        print(f"  proxy (explicit): {explicit}")
        return str(explicit).split(";")[0].split("=")[-1]
    if not pac:
        print("  no proxy configured")
        return None
    print(f"  PAC: {pac}")
    try:
        with urllib.request.urlopen(pac, timeout=10) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  could not fetch the PAC: {type(e).__name__}: {e}")
        return None
    hits = re.findall(r"PROXY\s+([A-Za-z0-9_.\-]+:\d+)", body)
    if not hits:
        print("  the PAC names no proxy - traffic goes direct")
        return None
    # A corporate PAC names dozens of proxies, nearly all of them for specific
    # sites in other countries. pypi.org matches none of those and falls
    # through to the default rule at the very bottom of the file. When the
    # agent runs a LOCAL proxy (Zscaler's ZAPP on 127.0.0.1), that is the one
    # the default rule hands back - so prefer it, and otherwise take the last
    # PROXY in the file, which is the default rule's.
    local = [h for h in hits if h.startswith("127.0.0.1")]
    chosen = local[0] if local else hits[-1]
    print(f"  proxy (from PAC): {chosen}   [{len(set(hits))} named in total]")
    return chosen


def write_bundle():
    """The machine's own trusted certificates as a PEM bundle pip can use.

    BOTH stores, not just ROOT. An inspection chain is normally leaf ->
    "<vendor> Intermediate Root CA" -> "<vendor> Root CA", and Windows files
    the intermediate under "CA", not "ROOT". Export ROOT alone and OpenSSL
    still cannot build the chain - it fails with exactly the error we are
    here to fix, "unable to get local issuer certificate", which looks like
    the bundle did not work at all.
    """
    out, counts = [], {}
    for store in ("ROOT", "CA"):
        try:
            certs = ssl.enum_certificates(store)   # Windows only
        except Exception as e:
            print(f"  no Windows '{store}' store ({type(e).__name__}) - skipping --cert")
            return None
        n = 0
        for der, enc, trust in certs:
            if enc != "x509_asn":
                continue
            b64 = base64.b64encode(der).decode()
            body = "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64))
            out.append(f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----\n")
            n += 1
        counts[store] = n
    if not out:
        print("  certificate stores were empty - skipping --cert")
        return None
    with open(BUNDLE, "w", encoding="ascii") as f:
        f.write("".join(out))
    print(f"  CA bundle: {counts.get('ROOT', 0)} root + {counts.get('CA', 0)} "
          f"intermediate -> {BUNDLE}")
    return BUNDLE


def main():
    print(__doc__)
    print("Working out how this machine reaches the internet:")
    proxy = proxy_from_pac()
    bundle = write_bundle()

    cmd = [sys.executable, "-m", "pip", "install"]
    if proxy:
        cmd += ["--proxy", f"http://{proxy}"]
    if bundle:
        cmd += ["--cert", bundle]
    if len(sys.argv) > 1:
        cmd += sys.argv[1:]
    else:
        cmd += ["-r", os.path.join(ENGINE, "requirements.txt")]

    print("\nRunning:\n  " + " ".join(cmd) + "\n")
    rc = subprocess.run(cmd).returncode
    if rc == 0:
        print("\nDone. Re-run:  python work_pc\\engine_preflight.py")
    else:
        print(f"\npip exited {rc}.")
        print("If it was CERTIFICATE_VERIFY_FAILED even with --cert, the")
        print("inspection CA is not in the machine's root store - ask IT for the")
        print("corporate root CA .pem. Last resort, which turns verification OFF")
        print("for those hosts only:")
        print("  pip install --proxy http://%s --trusted-host pypi.org "
              "--trusted-host files.pythonhosted.org -r requirements.txt"
              % (proxy or "PROXY:PORT"))
        print("If it could not connect at all, use the offline wheels - see")
        print("WORK_PC_MIGRATION.md section 4.1.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
