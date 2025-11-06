### Building and running your application

When you're ready, start your application by running:
`docker compose up --build`.

### Building for ARM architecture (Raspberry Pi)

To build for ARM architecture (e.g., Raspberry Pi), you have two options:

1. **Using Docker Compose** (recommended):
   - Uncomment the `platform: linux/arm64` line in `compose.yaml`
   - Run: `docker compose up --build`

2. **Using Docker directly**:
   ```bash
   docker build --platform=linux/arm64 -t well-bot .
   ```

**Important for ARM builds:**
- The Dockerfile automatically uses the ARM-specific wake word model (`WellBot_WakeWordModel_ARM.ppn`)
- Ensure your `.env` file includes `PORCUPINE_ACCESS_KEY_ARM` with your ARM-specific Picovoice access key
- The application will automatically detect ARM architecture and use the ARM key if available

### Deploying your application to the cloud

First, build your image, e.g.: `docker build -t myapp .`.
If your cloud uses a different CPU architecture than your development
machine (e.g., you are on a Mac M1 and your cloud provider is amd64),
you'll want to build the image for that platform, e.g.:
`docker build --platform=linux/amd64 -t myapp .`.

Then, push it to your registry, e.g. `docker push myregistry.com/myapp`.

Consult Docker's [getting started](https://docs.docker.com/go/get-started-sharing/)
docs for more detail on building and pushing.