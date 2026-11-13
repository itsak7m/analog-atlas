// Loads the JSON data files. Optional files (panoramas, terrain, assets, surface temperature, composition,
// EMIT minerals) may be missing: the feature that needs them is then switched off, nothing crashes.

async function getJSON(path, optional = false) {
  try {
    const res = await fetch(path, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    if (optional) return null;
    throw err;
  }
}

export async function loadData() {
  const [sitesDoc, targetsDoc, panoramas, terrainDoc, assets, powerDoc, resourcesDoc, streetDoc, lstDoc, compositionDoc, emitDoc] = await Promise.all([
    getJSON('data/sites.json'),
    getJSON('data/targets.json'),
    getJSON('data/panoramas.json', true),
    getJSON('data/terrain.json', true),
    getJSON('data/assets.json', true),
    getJSON('data/power_parameters.json', true),
    getJSON('data/resources.json', true),
    getJSON('data/streetview.json', true),
    getJSON('data/lst.json', true),
    getJSON('data/composition.json', true),
    getJSON('data/emit.json', true),
  ]);
  // MODIS land surface temperature for the "Ground surface" switch: site.lst (null when the site is not in the file).
  const lstPlaces = lstDoc && lstDoc.places && typeof lstDoc.places === 'object' ? lstDoc.places : null;
  for (const site of sitesDoc.sites) site.lst = lstPlaces ? lstPlaces[site.id] || null : null;
  return {
    sites: sitesDoc.sites,
    sitesDoc,
    targets: targetsDoc.targets,
    sources: targetsDoc.sources,
    panoramas,
    terrainDoc,
    terrain: terrainDoc ? terrainDoc.points : null,
    assets,
    powerDefs: powerDoc ? powerDoc.parameters : null,
    resourcesDoc,
    streetview: streetDoc ? streetDoc.places : {},
    lstDoc: lstPlaces ? lstDoc : null,
    compositionDoc: compositionDoc && compositionDoc.places ? compositionDoc : null,
    emitDoc: emitDoc && emitDoc.places && typeof emitDoc.places === 'object' ? emitDoc : null,
    // id -> list of resource tags, for the resources pillar
    resources: resourcesDoc ? Object.fromEntries(Object.entries(resourcesDoc.places).map(([id, p]) => [id, Object.keys(p.tags)])) : null,
  };
}

export const findSite = (data, id) => data.sites.find((s) => s.id === id) || null;
export const findTarget = (data, id) => data.targets.find((t) => t.id === id) || null;
