-- btmux-route.lua — variante Lua (WirePlumber 0.5) du routage exclusif source -> sink (spike #7).
--
-- Pilotage : une clé de métadonnées « btmux.route » dans l'objet « default » :
--   pw-metadata -n default 0 btmux.route "SOURCE_NODE_NAME>SINK_NODE_NAME" Spa:String
--   pw-metadata -n default 0 btmux.route "" Spa:String        (supprime la route)
-- Le script lie les ports par canal (une source mono est liée à tous les ports du sink), détruit les liens
-- de la source créés par d'autres (routage exclusif) et reconstruit tout seul la route quand les nœuds
-- réapparaissent (redémarrage de PipeWire/WirePlumber, reconnexion Bluetooth).
-- Installation : voir README.md (script dans ~/.local/share/wireplumber/scripts/ + composant 52-btmux-route.conf).
-- Provisoire — à revalider avec dongle RTL8761B.

local log = Log.open_topic ("s-btmux-route")

local desired = nil     -- { source = "...", sink = "..." }
local ours = {}         -- liens créés par ce script (références conservées = liens vivants)
local pending = false

local nodes_om = ObjectManager { Interest { type = "node" } }
local ports_om = ObjectManager { Interest { type = "port" } }
local links_om = ObjectManager { Interest { type = "link" } }
local metadata_om = ObjectManager {
  Interest { type = "metadata", Constraint { "metadata.name", "=", "default" } }
}

local function find_node (name)
  return nodes_om:lookup (Interest {
    type = "node", Constraint { "node.name", "=", name }
  })
end

local function ports_of (node, direction)
  local list = {}
  for port in ports_om:iterate (Interest {
    type = "port",
    Constraint { "node.id", "=", tostring (node["bound-id"]) },
    Constraint { "port.direction", "=", direction },
  }) do
    table.insert (list, port)
  end
  return list
end

local function channel (port)
  return port.properties["audio.channel"] or port.properties["port.name"]
end

local function pairs_for (outs, ins)
  local result = {}
  if #outs == 1 then
    for _, i in ipairs (ins) do table.insert (result, { outs[1], i }) end
    return result
  end
  for _, o in ipairs (outs) do
    for _, i in ipairs (ins) do
      if channel (o) == channel (i) then table.insert (result, { o, i }) end
    end
  end
  return result
end

local function is_ours (link)
  for _, l in ipairs (ours) do
    if l["bound-id"] == link["bound-id"] then return true end
  end
  return false
end

local function apply ()
  for i = #ours, 1, -1 do                      -- détruit explicitement nos anciens liens
    ours[i]:request_destroy ()
    ours[i] = nil
  end
  if not desired then return end
  local src, sink = find_node (desired.source), find_node (desired.sink)
  if not (src and sink) then
    log:info ("route en attente : nœud(s) absent(s)")
    return
  end
  local outs, ins = ports_of (src, "out"), ports_of (sink, "in")
  local wanted = pairs_for (outs, ins)
  if #wanted == 0 then return end
  -- Routage exclusif : détruit les liens de la source (ex. liés par défaut au sink par défaut)
  for link in links_om:iterate (Interest {
    type = "link",
    Constraint { "link.output.node", "=", tostring (src["bound-id"]) },
  }) do
    if not is_ours (link) then link:request_destroy () end
  end
  for _, pair in ipairs (wanted) do
    local link = Link ("link-factory", {
      ["link.output.node"] = src["bound-id"],
      ["link.output.port"] = pair[1]["bound-id"],
      ["link.input.node"] = sink["bound-id"],
      ["link.input.port"] = pair[2]["bound-id"],
      ["object.linger"] = false,
    })
    link:activate (Feature.Proxy.BOUND)
    table.insert (ours, link)
  end
  log:info (string.format ("route %s -> %s : %d lien(s)", desired.source, desired.sink, #wanted))
end

local function schedule ()           -- regroupe les rafales d'événements (ports ajoutés un par un)
  if pending then return end
  pending = true
  Core.timeout_add (20, function ()
    pending = false
    apply ()
    return false
  end)
end

local function parse (value)
  if not value or value == "" then desired = nil return end
  local s, k = value:match ("^([^>]+)>(.+)$")
  desired = s and { source = s, sink = k } or nil
end

metadata_om:connect ("object-added", function (_, metadata)
  parse (metadata:find (0, "btmux.route"))
  schedule ()
  metadata:connect ("changed", function (_, _, key, _, value)
    if key == "btmux.route" then
      parse (value)
      schedule ()
    end
  end)
end)

for _, om in ipairs { nodes_om, ports_om } do
  om:connect ("object-added", schedule)
  om:connect ("object-removed", schedule)
end

nodes_om:activate ()
ports_om:activate ()
links_om:activate ()
metadata_om:activate ()
