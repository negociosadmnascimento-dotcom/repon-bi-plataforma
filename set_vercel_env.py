import subprocess

# The correct DATABASE_URL for Supabase with the pooler endpoint
DATABASE_URL = "postgresql://postgres.mrwpgmwfbgffqxenflss:RepOn%40lplmult@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"

# Write to a temp file to pipe to vercel env add
with open("db_url_value.txt", "w") as f:
    f.write(DATABASE_URL)

print(f"DATABASE_URL ready: ...{DATABASE_URL[-60:]}")
print("Length:", len(DATABASE_URL))
