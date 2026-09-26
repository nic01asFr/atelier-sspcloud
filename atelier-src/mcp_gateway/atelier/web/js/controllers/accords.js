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

  return { activerAgent, desactiverAgent, accorderSecret };
}
