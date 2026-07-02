-- Enable UUID generation functions (built-in PostgreSQL contrib module)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable vector similarity search (installed via Dockerfile.documents-db)
CREATE EXTENSION IF NOT EXISTS "vector";
