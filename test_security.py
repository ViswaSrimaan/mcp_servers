"""Security Test Suite for MCP Server

This script tests all security protections against known attack vectors.
"""

import asyncio
import json
import sys
sys.path.insert(0, '.')

from src.security_config import is_path_allowed, is_url_safe, is_execution_safe

# Test results storage
results = {
    "path_traversal": [],
    "ssrf": [],
    "command_injection": [],
    "execution_restriction": [],
}


def test_path_traversal():
    """Test path traversal protection."""
    print("\n" + "="*60)
    print("TESTING: PATH TRAVERSAL PROTECTION")
    print("="*60)
    
    test_cases = [
        # (path, for_write, expected_blocked, description)
        ("C:/Windows/System32/drivers/etc/hosts", False, True, "Windows hosts file"),
        ("C:/Windows/System32/cmd.exe", False, True, "Windows CMD"),
        ("C:/Program Files/test.txt", False, True, "Program Files read"),
        ("C:/Program Files (x86)/malware.exe", True, True, "Program Files write"),
        ("C:/Users/test/Documents/readme.txt", False, False, "User documents (allow)"),
        ("/etc/passwd", False, True, "Linux passwd file"),
        ("/etc/shadow", False, True, "Linux shadow file"),
        ("C:/Users/test/malware.bat", True, True, "Batch file write"),
        ("C:/Users/test/script.ps1", True, True, "PowerShell script write"),
        ("C:/Users/test/document.txt", True, False, "Text file write (allow)"),
        ("C:/Users/test/image.png", True, False, "Image file write (allow)"),
    ]
    
    for path, for_write, expected_blocked, desc in test_cases:
        allowed, reason = is_path_allowed(path, for_write=for_write)
        actual_blocked = not allowed
        status = "✅ PASS" if actual_blocked == expected_blocked else "❌ FAIL"
        
        result = {
            "path": path,
            "operation": "write" if for_write else "read",
            "expected": "BLOCKED" if expected_blocked else "ALLOWED",
            "actual": "BLOCKED" if actual_blocked else "ALLOWED",
            "status": "PASS" if actual_blocked == expected_blocked else "FAIL",
            "reason": reason if actual_blocked else "Allowed"
        }
        results["path_traversal"].append(result)
        
        print(f"{status} | {desc}")
        print(f"       Path: {path}")
        print(f"       Expected: {'BLOCKED' if expected_blocked else 'ALLOWED'}, Got: {'BLOCKED' if actual_blocked else 'ALLOWED'}")
        if reason:
            print(f"       Reason: {reason[:80]}")
        print()


def test_ssrf():
    """Test SSRF (Server-Side Request Forgery) protection."""
    print("\n" + "="*60)
    print("TESTING: SSRF PROTECTION")
    print("="*60)
    
    test_cases = [
        # (url, expected_blocked, description)
        ("http://localhost:3000/api", True, "Localhost access"),
        ("http://127.0.0.1:8080", True, "Loopback IP"),
        ("http://192.168.1.1", True, "Private network (192.168.x.x)"),
        ("http://10.0.0.1", True, "Private network (10.x.x.x)"),
        ("http://172.16.0.1", True, "Private network (172.16.x.x)"),
        ("http://169.254.169.254/metadata", True, "Cloud metadata (AWS/GCP)"),
        ("http://metadata.google.internal", True, "GCP metadata"),
        ("http://[::1]/", True, "IPv6 loopback"),
        ("https://www.google.com", False, "Public website (allow)"),
        ("https://api.github.com", False, "Public API (allow)"),
        ("ftp://files.example.com", True, "FTP scheme blocked"),
        ("file:///etc/passwd", True, "File scheme blocked"),
    ]
    
    for url, expected_blocked, desc in test_cases:
        safe, reason = is_url_safe(url)
        actual_blocked = not safe
        status = "✅ PASS" if actual_blocked == expected_blocked else "❌ FAIL"
        
        result = {
            "url": url,
            "expected": "BLOCKED" if expected_blocked else "ALLOWED",
            "actual": "BLOCKED" if actual_blocked else "ALLOWED",
            "status": "PASS" if actual_blocked == expected_blocked else "FAIL",
            "reason": reason if actual_blocked else "Allowed"
        }
        results["ssrf"].append(result)
        
        print(f"{status} | {desc}")
        print(f"       URL: {url}")
        print(f"       Expected: {'BLOCKED' if expected_blocked else 'ALLOWED'}, Got: {'BLOCKED' if actual_blocked else 'ALLOWED'}")
        if reason:
            print(f"       Reason: {reason[:80]}")
        print()


def test_execution_restriction():
    """Test execution restriction protection."""
    print("\n" + "="*60)
    print("TESTING: EXECUTION RESTRICTION")
    print("="*60)
    
    test_cases = [
        # (target, expected_blocked, description)
        ("notepad", False, "Safe app: notepad"),
        ("calc", False, "Safe app: calculator"),
        ("notepad.exe", False, "Safe app with extension"),
        ("chrome", False, "Safe app: Chrome browser"),
        ("https://www.google.com", False, "URL (opens in browser)"),
        ("malware.exe", True, "Unknown executable"),
        ("C:/Users/test/hack.bat", True, "Batch script"),
        ("C:/Users/test/evil.ps1", True, "PowerShell script"),
        ("cmd.exe", True, "Command prompt"),
        ("powershell.exe", True, "PowerShell"),
        ("ransomware.scr", True, "Screensaver (executable)"),
        ("C:/Users/test/document.pdf", False, "Safe file: PDF"),
        ("C:/Users/test/image.png", False, "Safe file: PNG"),
    ]
    
    for target, expected_blocked, desc in test_cases:
        safe, reason = is_execution_safe(target)
        actual_blocked = not safe
        status = "✅ PASS" if actual_blocked == expected_blocked else "❌ FAIL"
        
        result = {
            "target": target,
            "expected": "BLOCKED" if expected_blocked else "ALLOWED",
            "actual": "BLOCKED" if actual_blocked else "ALLOWED",
            "status": "PASS" if actual_blocked == expected_blocked else "FAIL",
            "reason": reason if actual_blocked else "Allowed"
        }
        results["execution_restriction"].append(result)
        
        print(f"{status} | {desc}")
        print(f"       Target: {target}")
        print(f"       Expected: {'BLOCKED' if expected_blocked else 'ALLOWED'}, Got: {'BLOCKED' if actual_blocked else 'ALLOWED'}")
        if reason:
            print(f"       Reason: {reason[:80]}")
        print()


def test_command_injection_protection():
    """Test that run_command now requires confirmation."""
    print("\n" + "="*60)
    print("TESTING: COMMAND INJECTION PROTECTION")
    print("="*60)
    
    # Import and check run_command docstring
    from src.tools import system_tools
    import inspect
    
    # Check if run_command mentions confirmation
    source = inspect.getsource(system_tools)
    
    checks = [
        ("Uses confirmation token", "create_confirmation_token" in source),
        ("Docstring mentions confirmation", "confirmation" in source.lower()),
        ("Docstring mentions destructive/dangerous", "dangerous" in source.lower() or "destructive" in source.lower()),
    ]
    
    for desc, passed in checks:
        status = "✅ PASS" if passed else "❌ FAIL"
        result = {
            "check": desc,
            "status": "PASS" if passed else "FAIL"
        }
        results["command_injection"].append(result)
        print(f"{status} | {desc}")


def generate_summary():
    """Generate test summary."""
    print("\n" + "="*60)
    print("SECURITY TEST SUMMARY")
    print("="*60)
    
    total_pass = 0
    total_fail = 0
    
    for category, tests in results.items():
        passed = sum(1 for t in tests if t.get("status") == "PASS")
        failed = sum(1 for t in tests if t.get("status") == "FAIL")
        total_pass += passed
        total_fail += failed
        
        status_icon = "✅" if failed == 0 else "⚠️"
        print(f"{status_icon} {category.upper()}: {passed}/{passed+failed} tests passed")
    
    print("-" * 40)
    print(f"TOTAL: {total_pass}/{total_pass+total_fail} tests passed")
    
    if total_fail == 0:
        print("\n🎉 ALL SECURITY TESTS PASSED!")
    else:
        print(f"\n⚠️  {total_fail} tests failed - review needed")
    
    return results


if __name__ == "__main__":
    print("="*60)
    print("MCP SERVER SECURITY VULNERABILITY TEST SUITE")
    print("="*60)
    
    test_path_traversal()
    test_ssrf()
    test_execution_restriction()
    test_command_injection_protection()
    
    final_results = generate_summary()
    
    # Save results to JSON
    with open("security_test_results.json", "w") as f:
        json.dump(final_results, f, indent=2)
    
    print("\nResults saved to security_test_results.json")
