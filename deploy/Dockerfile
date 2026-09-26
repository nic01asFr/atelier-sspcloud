# L'image de l'Atelier pour le catalogue Onyxia.
#
# Même base que le service Jupyter du catalogue officiel : même Python, même
# utilisateur `onyxia`, même volume ~/work. Node, code-server, wikichat et le
# paquet de l'Atelier sont posés ici sous /opt/atelier. Le navigateur et
# l'extension Claude Code, soumis aux conditions de leurs éditeurs, ne sont
# pas redistribués dans l'image : l'init les télécharge depuis leur source au
# premier démarrage et les garde sur le volume.
FROM inseefrlab/onyxia-jupyter-python:py3.13.13

ARG NODE_VERSION=22.23.2
ARG CODE_SERVER_VERSION=4.135.0
ARG WIKICHAT_DEPOT=https://github.com/nic01asFr/wikichat.git
ARG WIKICHAT_REF=main
ARG GIT_SHA=

USER root
ENV ATELIER_OUTILS=/opt/atelier/outils
RUN mkdir -p "$ATELIER_OUTILS" /opt/atelier/bin

# node et npm, épinglés.
RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
      -o /tmp/node.tar.xz \
    && tar -xJf /tmp/node.tar.xz -C "$ATELIER_OUTILS" \
    && rm -f /tmp/node.tar.xz
ENV ATELIER_NODE_DIR=/opt/atelier/outils/node-v${NODE_VERSION}-linux-x64
ENV PATH=${ATELIER_NODE_DIR}/bin:${PATH}

# code-server, épinglé. L'extension Claude Code — et donc le binaire `claude`
# qu'elle apporte — sera installée par atelier-init.sh sur le volume.
RUN curl -fsSL "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server-${CODE_SERVER_VERSION}-linux-amd64.tar.gz" \
      -o /tmp/code-server.tar.gz \
    && tar -xzf /tmp/code-server.tar.gz -C "$ATELIER_OUTILS" \
    && rm -f /tmp/code-server.tar.gz
ENV ATELIER_CODE_SERVER_DIR=/opt/atelier/outils/code-server-${CODE_SERVER_VERSION}-linux-amd64

# Le navigateur sans écran sera téléchargé sur le volume au premier démarrage.
# L'image ne garde que ses bibliothèques système (liste Debian/Ubuntu publiée
# par Puppeteer) et le serveur MCP épinglé. Chaque agent le lance par
# ~/work/bin/atelier-chrome, en stdio (docs/navigateur-atelier.md).
ARG CHROME_MCP_VERSION=1.10.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates fonts-liberation libasound2t64 libatk-bridge2.0-0t64 \
      libatk1.0-0t64 libcairo2 libcups2t64 libdbus-1-3 libexpat1 libfontconfig1 \
      libgbm1 libglib2.0-0t64 libgtk-3-0t64 libnspr4 libnss3 libpango-1.0-0 \
      libpangocairo-1.0-0 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 \
      libxcursor1 libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 \
      libxrender1 libxss1 libxtst6 xdg-utils \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p "$ATELIER_OUTILS/chrome-devtools-mcp" \
    && npm install --prefix "$ATELIER_OUTILS/chrome-devtools-mcp" --no-audit --no-fund \
      --save-exact "chrome-devtools-mcp@${CHROME_MCP_VERSION}"

# wikichat et ses dépendances.
RUN git clone -q --depth 1 --branch "$WIKICHAT_REF" "$WIKICHAT_DEPOT" /opt/atelier/wikichat \
    && cd /opt/atelier/wikichat \
    && npm ci --omit=dev --no-audit --no-fund
ENV WIKICHAT_SRC=/opt/atelier/wikichat

# L'Atelier lui-même.
COPY atelier-src /opt/atelier/src
RUN pip install --quiet --no-cache-dir -e /opt/atelier/src
ENV ATELIER_SRC=/opt/atelier/src
COPY install/atelier-init.sh /opt/atelier/bin/atelier-init.sh
RUN chmod +x /opt/atelier/bin/atelier-init.sh \
    && printf '%s' "$GIT_SHA" > /opt/atelier/VERSION \
    && chown -R onyxia:users /opt/atelier

USER onyxia
WORKDIR /home/onyxia
# Le code est dans l'image ; les deux outils tiers sont installés sur le volume.
ENV ATELIER_DEPOT="" \
    WIKICHAT_DEPOT="" \
    ATELIER_AVANT_PLAN=1 \
    ATELIER_WORK=/home/onyxia/work

EXPOSE 8787
ENTRYPOINT ["bash", "/opt/atelier/bin/atelier-init.sh"]
