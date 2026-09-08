CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255)
);

CREATE UNIQUE INDEX idx_users_email ON users (email);
