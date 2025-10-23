## Running the Project with Docker

This project provides Docker and Docker Compose configurations to run the Python backend in a reproducible environment.

### Project-Specific Docker Requirements
- **Python Version:** 3.13 (as specified in the Dockerfile)
- **Dependencies:** Installed from `backend/requirements.txt` inside a Python virtual environment (`venv`).

### Environment Variables
- No environment variables are strictly required by default. If you use a `.env` file for configuration, uncomment the `env_file` line in the `docker-compose.yml` and place your `.env` file in the `backend/` directory.

### Build and Run Instructions
1. **Build and start the backend service:**
   ```sh
   docker compose up --build
   ```
   This will build the image using the provided Dockerfile and start the backend service.

2. **Stopping the service:**
   ```sh
   docker compose down
   ```

### Special Configuration
- The backend runs as a non-root user (`backenduser`) for improved security.
- All Python dependencies are installed in a virtual environment, isolated from the system Python.
- If you need to connect to external services (e.g., Postgres, Redis), uncomment and configure the relevant sections in `docker-compose.yml`.

### Ports
- **No ports are exposed by default.**
  - If your backend listens on a port (e.g., 8000), uncomment and configure the `ports` section in `docker-compose.yml` and the `EXPOSE` line in the Dockerfile.

### Additional Notes
- If you add database or cache services, also uncomment the `depends_on` and `networks` sections as needed.
- For environment-specific configuration, use a `.env` file and reference it in the compose file.

---
*This section was updated to reflect the current Docker setup for the backend. Please ensure your local configuration matches any changes you make to the Docker or Compose files.*