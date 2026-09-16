# L'image de l'Atelier pour le catalogue Onyxia.
#
# Même base que le service Jupyter du catalogue officiel : même Python, même
# utilisateur `onyxia`, même volume ~/work. Ce qui est lourd ou vient du
# réseau — node, code-server, l'extension Claude Code, wikichat et ses
# dépendances, le paquet de l'Atelier — est posé ici, une fois, sous
# /opt/atelier. Au démarrage du pod, install/atelier-init.sh n'a plus que les
# secrets, les réglages et les processus à poser, sur le volume.
FROM inseefrlab/onyxia-jupyter-python:py3.13.13

ARG NODE_VERSION=22.23.2
ARG CODE_SERVER_VERSION=4.135.0
ARG WIKICHAT_DEPOT=https://github.com/nic01asFr/wikichat.git
ARG WIKICHAT_REF=main
ARG GIT_SHA=

USER root
ENV ATELIER_OUTILS=/opt/atelier/outils
RUN mkdir -p "$ATELIER_OUTILS" /opt/atelier/extensions /opt/atelier/bin

# node et npm, épinglés.
RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
      -o /tmp/node.tar.xz \
    && tar -xJf /tmp/node.tar.xz -C "$ATELIER_OUTILS" \
    && rm -f /tmp/node.tar.xz
ENV ATELIER_NODE_DIR=/opt/atelier/outils/node-v${NODE_VERSION}-linux-x64
ENV PATH=${ATELIER_NODE_DIR}/bin:${PATH}

# code-server, épinglé, et l'extension Claude Code — c'est d'elle que vient
# le binaire `claude`.
RUN curl -fsSL "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server-${CODE_SERVER_VERSION}-linux-amd64.tar.gz" \
      -o /tmp/code-server.tar.gz \
    && tar -xzf /tmp/code-server.tar.gz -C "$ATELIER_OUTILS" \
    && rm -f /tmp/code-server.tar.gz
ENV ATELIER_CODE_SERVER_DIR=/opt/atelier/outils/code-server-${CODE_SERVER_VERSION}-linux-amd64
ENV ATELIER_EXTENSIONS=/opt/atelier/extensions
RUN "$ATELIER_CODE_SERVER_DIR/bin/code-server" --extensions-dir "$ATELIER_EXTENSIONS" \
      --install-extension anthropic.claude-code --force \
    && ls -d "$ATELIER_EXTENSIONS"/anthropic.claude-code-* \
    && test -x "$(ls -d "$ATELIER_EXTENSIONS"/anthropic.claude-code-* | sort -V | tail -1)/resources/native-binary/claude"

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
# Rien à cloner ni à télécharger au démarrage : tout est dans l'image.
ENV ATELIER_DEPOT="" \
    WIKICHAT_DEPOT="" \
    ATELIER_AVANT_PLAN=1 \
    ATELIER_WORK=/home/onyxia/work

EXPOSE 8787
ENTRYPOINT ["bash", "/opt/atelier/bin/atelier-init.sh"]
