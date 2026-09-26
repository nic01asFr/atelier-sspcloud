import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ancresDe, liensDe, slugDeTitre, verifier } from "./verifier-liens.mjs";

test("slugDeTitre suit GitHub, accents et guillemets compris", () => {
  assert.equal(slugDeTitre("6. « À valider », journal, annulation"), "6--à-valider--journal-annulation");
  assert.equal(slugDeTitre("Profils d'accès"), "profils-daccès");
  assert.equal(slugDeTitre("`code` et **gras**"), "code-et-gras");
});

test("ancresDe numérote les titres répétés et ignore les blocs de code", () => {
  const a = ancresDe("# Titre\n## Titre\n```\n# pas un titre\n```\n<a id=\"ici\"></a>\n");
  assert.deepEqual([...a].sort(), ["ici", "titre", "titre-1"]);
});

test("liensDe ignore le code en ligne et les blocs", () => {
  const l = liensDe("[a](b.md) `[c](d.md)`\n```\n[e](f.md)\n```\n<img src=\"g.png\">");
  assert.deepEqual(l.map((x) => x.cible), ["b.md", "g.png"]);
});

test("verifier signale un fichier et une ancre absents, pas un lien externe", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "liens-"));
  fs.writeFileSync(path.join(dir, "a.md"), "# Bonjour\n[ok](b.md#suite) [ko](c.md) [ancre](b.md#rien) [web](https://exemple.org)\n");
  fs.writeFileSync(path.join(dir, "b.md"), "## Suite\n");
  assert.deepEqual(verifier(["a.md"], dir), ["a.md:2 : c.md (fichier absent)", "a.md:2 : b.md#rien (ancre absente)"]);
});
