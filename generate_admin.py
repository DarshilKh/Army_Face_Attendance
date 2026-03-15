from werkzeug.security import generate_password_hash
import pymysql
import os

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Consistent password (same as app.py CLI create_admin command)
password = "Admin@123"

# Hash generate (same method as app.py)
password_hash = generate_password_hash(password, method='scrypt')

print(f"Generated hash for password '{password}':")
print(password_hash)
print("\n--- SQL Query ---")
print(f"""
UPDATE users 
SET password_hash = '{password_hash}' 
WHERE username = 'admin';
""")

# Database me directly update karo (optional)
try:
    conn = pymysql.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'army_attendance')
    )
    cursor = conn.cursor()

    # Old admin delete
    cursor.execute("DELETE FROM users WHERE username='admin'")

    # New admin insert
    cursor.execute("""
                   INSERT INTO users (username, password_hash, full_name, `rank`, role, email, is_active, failed_login_attempts)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   """, ('admin', password_hash, 'System Administrator', 'Major', 'admin', 'admin@army.mil.in', 1, 0))

    conn.commit()
    print("\n✓ Admin user created successfully!")
    print(f"Username: admin")
    print(f"Password: {password}")

    cursor.close()
    conn.close()
except Exception as e:
    print(f"\n✗ Error: {e}")
    print("\nManually run this SQL:")
    print(f"UPDATE users SET password_hash = '{password_hash}' WHERE username = 'admin';")
