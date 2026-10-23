/**
 * Les accords de la personne : activer un agent, accorder un secret.
 *
 * Deux commandes réservées de l'équipe K (`atelier_agent_activer`,
 * `atelier_connecteur_accorder`) : un modèle ne peut pas les appeler, la
 * session de l'interface si. Rien ici ne voit une valeur de secret : on
 * choisit un nom de fichier, le serveur lit le fichier.
 */

import * as S from "../state.js";

export const ACTIVER_AGENT = "atelier_agent_activer";
export const DESACTIVER_AGENT = "atelier_agent_desactiver";
export const ACCORDER_SECRET = "atelier_connecteur_accorder";
export const RENOUVELER_SECRET = "atelier_connecteur_renouveler";
export const MODIFIER_CONNECTEUR = "atelier_connecteur_modifier";

/** Un connecteur local reçoit une variable, un service distant un en-tête. */
export function blocDuConnecteur(entry) {
  return entry?.config?.command || entry?.runtime === "stdio" ? "env" : "headers";
}

/** Les champs de la fenêtre « Accorder un secret ». */
export function champsPourAccorder(entry, noms) {
  const bloc = blocDuConnecteur(entry);
  const options = [{ value: "", label: noms.length ? "Choisir un secret…" : "Aucun secret disponible" }];
  for (const n of noms) {
    options.push({ value: n.nom, label: n.protege ? n.nom : `${n.nom} (à protéger : chmod 600)` });
  }
  return [
    {
      name: "secret",
      label: "Secret",
      type: "select",
      options,
      hint: "Un fichier du dossier des secrets. Sa valeur ne passe jamais par l’écran : l’Atelier la lit lui-même.",
      required: true,
      full: true,
    },
    {
      name: "cle",
      label: bloc === "env" ? "Variable" : "En-tête",
      placeholder: bloc === "env" ? "API_KEY" : "Authorization",
      value: bloc === "env" ? "" : "Authorization",
      hint:
        bloc === "env"
          ? "Le nom de la variable que le connecteur lit au démarrage."
          : "L’en-tête envoyé au service à chaque appel.",
      required: true,
    },
    {
      name: "schema",
      label: "Préfixe",
      type: "select",
      value: bloc === "env" ? "" : "Bearer",
      options: [
        { value: "", label: "Aucun" },
        { value: "Bearer", label: "Bearer" },
        { value: "Token", label: "Token" },
        { value: "Basic", label: "Basic" },
      ],
      hint: "Ce qui précède la valeur, si le service l’attend.",
    },
  ];
}

/** Les champs de la fenêtre « Modifier » : l'adresse et le transport actuels. */
export function champsPourModifier(entry) {
  const type = entry?.config?.type;
  return [
    {
      name: "url", label: "Adresse", type: "text", value: entry?.config?.url || entry?.url || "", required: true, full: true,
      placeholder: "https://…", hint: "http:// ou https://. La barre finale compte pour certains services.",
    },
    {
      name: "transport", label: "Transport", type: "select", value: type === "sse" ? "sse" : "http",
      options: [{ value: "http", label: "http (streamable)" }, { value: "sse", label: "sse" }],
      hint: "Presque toujours http ; sse pour un ancien service à flux d’événements.",
    },
  ];
}

/** Les arguments de la commande de modification ; seuls les champs qui changent partent. */
export function argumentsDeModification(entry, data) {
  const url = String(data?.url || "").trim();
  if (!/^https?:\/\//.test(url)) throw new Error("L’adresse commence par http:// ou https://.");
  const args = { nom: entry.id || entry.name };
  if (url !== (entry?.config?.url || entry?.url || "")) args.url = url;
  const transport = String(data?.transport || "").trim();
  if (transport && transport !== (entry?.config?.type === "sse" ? "sse" : "http")) args.transport = transport;
  if (!args.url && !args.transport) throw new Error("Rien à modifier : l’adresse et le transport sont déjà ceux-là.");
  return args;
}

/** Les arguments de la commande, depuis la saisie ; lève si elle est incomplète. */
export function argumentsDAccord(entry, data) {
  const bloc = blocDuConnecteur(entry);
  const cle = String(data?.cle || "").trim();
  const secret = String(data?.secret || "").trim();
  if (!secret) throw new Error("Choisissez un secret.");
  if (!/^[A-Za-z0-9_.-]{1,64}$/.test(cle)) {
    throw new Error(bloc === "env" ? "Nom de variable invalide." : "Nom d’en-tête invalide.");
  }
  const args = { nom: entry.id || entry.name, champ: `${bloc}.${cle}`, secret };
  if (data?.schema) args.schema = data.schema;
  return args;
}

/**
 * @param {object} ctx
 * @param {object} ctx.state
 * @param {object} ctx.api  executerCommande, listerNomsDesSecrets
 * @param {() => void} ctx.render
 * @param {Function} ctx.openModal  (state, opts)
 * @param {() => Promise<void>} [ctx.apresAgent]  relire les agents
 * @param {() => Promise<void>} [ctx.apresConnecteur]  relire les connecteurs
 */
export function createAccordsActions(ctx) {
  const { state, api, render } = ctx;

  async function basculerAgent(agentId, activer) {
    try {
      await api.executerCommande(activer ? ACTIVER_AGENT : DESACTIVER_AGENT, { agent: agentId });
      S.setError(state, "");
    } catch (err) {
      if (err?.status === 401) return ctx.logout?.("Clé invalide");
      S.setError(state, err?.message || String(err));
    }
    await ctx.apresAgent?.();
    render();
  }

  const activerAgent = (agentId) => basculerAgent(agentId, true);
  const desactiverAgent = (agentId) => basculerAgent(agentId, false);

  async function accorderSecret(entry) {
    let noms = [];
    try {
      noms = (await api.listerNomsDesSecrets())?.noms || [];
    } catch (err) {
      if (err?.status === 401) return ctx.logout?.("Clé invalide");
      S.setError(state, err?.message || String(err));
      render();
      return;
    }
    ctx.openModal(state, {
      title: `Accorder un secret à « ${entry.name || entry.id} »`,
      lead:
        "Le connecteur recevra la valeur du fichier choisi. Les projets n’en voient qu’une référence ; ni le journal ni l’écran ne la montrent.",
      submitLabel: "Accorder",
      fields: champsPourAccorder(entry, noms),
      onSubmit: async (data) => {
        await api.executerCommande(ACCORDER_SECRET, argumentsDAccord(entry, data));
        await ctx.apresConnecteur?.();
        render();
      },
    });
  }

  /**
   * Un accord copie la valeur du fichier au moment où on l'accorde : après un jeton renouvelé, on relit les fichiers.
   * Le résultat ne porte que des noms : la fenêtre dit quels connecteurs ont reçu la nouvelle valeur.
   */
  async function renouvelerSecret(entry) {
    const nom = entry.id || entry.name;
    let rendu;
    try {
      rendu = await api.executerCommande(RENOUVELER_SECRET, { nom });
    } catch (err) {
      if (err?.status === 401) return ctx.logout?.("Clé invalide");
      S.setError(state, err?.message || String(err));
      render();
      return;
    }
    S.setError(state, "");
    const charge = rendu?.resultat || rendu?.charge || {};
    const faits = Array.isArray(charge.renouveles) ? charge.renouveles : [];
    const illisibles = (Array.isArray(charge.details) ? charge.details : []).filter((d) => d.etat === "illisible");
    const lignes = [];
    lignes.push(faits.length ? `Renouvelé : ${faits.join(", ")}.` : "Le fichier du secret n’a pas changé : le connecteur a déjà la bonne valeur.");
    for (const d of illisibles) lignes.push(`${d.secret} : ${d.motif}`);
    ctx.openModal(state, {
      title: `Secrets de « ${entry.name || entry.id} »`,
      lead: lignes.join(" "),
      submitLabel: "Fermer",
      fields: [],
      onSubmit: async () => {},
    });
    await ctx.apresConnecteur?.();
    render();
  }

  /**
   * Changer l'adresse ou le transport d'un service distant sans le supprimer : ses secrets accordés et son état restent.
   * La fenêtre prévient qu'un secret accordé part vers la nouvelle adresse.
   */
  function modifierConnecteur(entry) {
    const nom = entry.id || entry.name;
    ctx.openModal(state, {
      title: `Modifier « ${entry.name || entry.id} »`,
      lead:
        "Change l’adresse ou le transport sans supprimer le connecteur : les secrets déjà accordés et l’état restent. " +
        "Un secret accordé est envoyé à la nouvelle adresse : ne la changez que pour un hôte de confiance.",
      submitLabel: "Modifier",
      fields: champsPourModifier(entry),
      onSubmit: async (data) => {
        const args = argumentsDeModification(entry, data);
        const rendu = await api.executerCommande(MODIFIER_CONNECTEUR, args);
        await ctx.apresConnecteur?.();
        render();
        const sonde = rendu?.resultat?.sonde || rendu?.charge?.sonde;
        if (sonde && sonde.online === false && sonde.error) S.setError(state, `Modifié, mais le connecteur ne répond pas encore : ${sonde.error}`);
      },
    });
  }

  return { activerAgent, desactiverAgent, accorderSecret, renouvelerSecret, modifierConnecteur };
}
