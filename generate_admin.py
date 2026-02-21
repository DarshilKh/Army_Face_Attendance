from werkzeug.security import generate_password_hash
import pymysql

# Password jo set karna hai
password = "admin123"

# Hash generate karo
password_hash = generate_password_hash(password, method='pbkdf2:sha256')

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
        host='localhost',
        user='root',  # Your MySQL username
        password='123@',  # Your MySQL password
        database='army_attendance'
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
