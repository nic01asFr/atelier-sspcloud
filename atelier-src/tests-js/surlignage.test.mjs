// Le surlignage ne doit jamais déchirer son propre balisage.
//
// Mesuré : les règles s'appliquaient l'une après l'autre sur le HTML déjà
// produit, et la règle des chaînes trouvait ses guillemets dans
// `class="hl-kw"`. L'écran montrait `"hl-kw">python` en clair au milieu des
// sorties d'outils.

import { test } from "node:test";
import assert from "node:assert/strict";

import { highlightCode } from "../mcp_gateway/atelier/web/js/ui/code-highlight.js";

test("un mot-clé dans un chemin ne déchire pas le balisage", () => {
  const html = highlightCode("/opt/python/bin/python: No module named pytest", "bash");
  assert.ok(html.includes('<span class="hl-kw">python</span>'));
  assert.ok(!html.includes('"hl-kw">python/'), "plus de balise ouverte en clair");
  assert.equal((html.match(/<span/g) || []).length, (html.match(/<\/span>/g) || []).length);
});

test("une chaîne protège ce qu'elle contient", () => {
  const html = highlightCode('echo "python" # note', "bash");
  assert.ok(html.includes('<span class="hl-str">"python"</span>'));
  assert.ok(!html.includes('hl-kw">python'), "pas de mot-clé colorié dans une chaîne");
});

test("le JSON colore chaînes, mots-clés et nombres", () => {
  const html = highlightCode('{"a": true, "b": 12}', "json");
  assert.ok(html.includes('<span class="hl-str">"a"</span>'));
  assert.ok(html.includes('<span class="hl-kw">true</span>'));
  assert.ok(html.includes('<span class="hl-num">12</span>'));
});

test("le HTML est échappé avant tout", () => {
  const html = highlightCode("<script>alert(1)</script>", "bash");
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
});

test("un langage inconnu rend le texte échappé tel quel", () => {
  assert.equal(highlightCode("a < b", "cobol"), "a &lt; b");
});
