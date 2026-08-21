-- ==============================================================================
-- Pokemon HeartGold (KOR) - Precision Target Lock Engine v14.0
-- Author: Antigravity Pair Programmer
-- ==============================================================================

local socket_ok, socket = pcall(require, "socket")
local udp = nil

if socket_ok then
    udp = socket.udp()
    udp:setpeername("127.0.0.1", 8765)
    udp:settimeout(0)
    print("[bHaptics Lua] UDP connected to 127.0.0.1:8765")
end

local temp_path = os.getenv("TEMP") or "C:\\Windows\\Temp"
local state_file_path = temp_path .. "\\hgss_hp_state.json"

local locked_hp_addr = 0
local locked_max_hp_addr = 0
local locked_tag = "None"

local last_hp = -1
local last_max_hp = -1
local last_hit_ratio = 0.0
local last_hit_time = 0
local frame_count = 0

local function send_damage_event(damage_ratio, is_fainted, cur_hp, max_hp)
    if udp then
        local payload = string.format(
            '{"damage_ratio": %.4f, "is_fainted": %s, "cur_hp": %d, "max_hp": %d}',
            damage_ratio,
            is_fainted and "true" or "false",
            cur_hp,
            max_hp
        )
        udp:send(payload)
        print(string.format(">>> [HIT TRIGGERED] -%.1f%% | HP: %d/%d | Fainted: %s", 
                            damage_ratio * 100, cur_hp, max_hp, tostring(is_fainted)))
    end

    -- Also write to %TEMP%\hgss_hp_state.json for multi-bridge compatibility
    local f = io.open(state_file_path, "w")
    if f then
        f:write(string.format('{"cur_hp": %d, "max_hp": %d, "damage_ratio": %.4f, "is_fainted": %s, "timestamp": %d}',
                              cur_hp, max_hp, damage_ratio, is_fainted and "true" or "false", frame_count))
        f:close()
    end
end

-- Any-order Move Matching: Finds any structure containing Tackle(33) and Growl(45)
local function search_chikorita()
    -- Scan battle RAM
    for addr = 0x02200000, 0x022A0000, 2 do
        local m1 = memory.readword(addr)
        local m2 = memory.readword(addr + 2)
        local m3 = memory.readword(addr + 4)
        local m4 = memory.readword(addr + 6)

        local has_tackle = (m1 == 33 or m2 == 33 or m3 == 33 or m4 == 33)
        local has_growl  = (m1 == 45 or m2 == 45 or m3 == 45 or m4 == 45)
        local has_leaf   = (m1 == 75 or m2 == 75 or m3 == 75 or m4 == 75)

        if (has_tackle and has_growl) or (has_tackle and has_leaf) then
            -- Test offsets around the move block
            for _, off in ipairs({16, 18, 20, 24, 0x10, 0x18, -16, -20}) do
                local cur_hp = memory.readword(addr + off)
                local max_hp = memory.readword(addr + off + 2)

                if max_hp >= 10 and max_hp <= 200 and cur_hp <= max_hp and cur_hp >= 0 then
                    print(string.format(">>> [LOCKED CHIKORITA] Addr 0x%08X (Offset %+d) | HP: %d/%d", addr + off, off, cur_hp, max_hp))
                    return (addr + off), (addr + off + 2), cur_hp, max_hp, "Battle (Tackle/Growl/Leaf)"
                end
            end
        end
    end

    -- Priority 2: Static Base Pointer Dereferencing
    local POINTERS = {0x021D41C4, 0x021D41A4, 0x021D3F84, 0x021118A8, 0x02111888, 0x02113ACC, 0x02113B50}
    for _, ptr_addr in ipairs(POINTERS) do
        local ptr = memory.readdword(ptr_addr)
        if ptr >= 0x02000000 and ptr <= 0x023E0000 then
            for _, off in ipairs({0x10, 0x18, 0x24, 0xD0 + 0x8E, 0xE0 + 0x8E, 0x8E}) do
                local cur_hp = memory.readword(ptr + off)
                local max_hp = memory.readword(ptr + off + 2)
                if max_hp >= 10 and max_hp <= 200 and cur_hp <= max_hp and cur_hp >= 0 then
                    print(string.format(">>> [LOCKED VIA POINTER] 0x%08X (+0x%X) | HP: %d/%d", ptr_addr, off, cur_hp, max_hp))
                    return (ptr + off), (ptr + off + 2), cur_hp, max_hp, string.format("Pointer (0x%08X)", ptr_addr)
                end
            end
        end
    end

    return 0, 0, -1, -1, "None"
end

gui.register(function()
    frame_count = frame_count + 1

    local cur_hp = -1
    local max_hp = -1

    -- If locked, read directly (0.0001 ms per frame, 0% CPU, 60 FPS!)
    if locked_hp_addr ~= 0 then
        local c = memory.readword(locked_hp_addr)
        local m = memory.readword(locked_max_hp_addr)
        if m >= 10 and m <= 200 and c <= m and c >= 0 then
            cur_hp = c
            max_hp = m
        else
            locked_hp_addr = 0
            locked_max_hp_addr = 0
        end
    end

    -- If not locked, scan once every 30 frames (~0.5s)
    if locked_hp_addr == 0 and (frame_count % 30 == 0) then
        local h_addr, m_addr, c_val, m_val, tag = search_chikorita()
        if h_addr ~= 0 then
            locked_hp_addr = h_addr
            locked_max_hp_addr = m_addr
            cur_hp = c_val
            max_hp = m_val
            locked_tag = tag
        end
    end

    -- Damage Detection
    if cur_hp ~= -1 and max_hp ~= -1 then
        if last_hp ~= -1 and last_max_hp == max_hp then
            if cur_hp < last_hp then
                local damage = last_hp - cur_hp
                local damage_ratio = damage / max_hp
                local is_fainted = (cur_hp == 0)

                last_hit_ratio = damage_ratio
                last_hit_time = frame_count

                send_damage_event(damage_ratio, is_fainted, cur_hp, max_hp)
            end
        end
        last_hp = cur_hp
        last_max_hp = max_hp

        -- Draw HUD
        local pct = (cur_hp / max_hp) * 100
        local color = "green"
        if pct <= 20 then color = "red"
        elseif pct <= 50 then color = "yellow" end

        gui.text(6, 6, string.format("TactSuit HGSS [KOR] | HP: %d/%d (%d%%)", cur_hp, max_hp, math.floor(pct)), color, "black")
        gui.text(6, 18, string.format("Locked: %s", locked_tag), "cyan", "black")

        if (frame_count - last_hit_time) < 120 and last_hit_ratio > 0 then
            gui.text(6, 30, string.format(">> HIT DETECTED: -%.1f%% DAMAGE! <<", last_hit_ratio * 100), "red", "white")
        end
    else
        gui.text(6, 6, "TactSuit HGSS [KOR] | Searching Pokemon...", "yellow", "black")
    end
end)

print("==========================================================")
print("  HGSS KOR Precision Target Lock Engine v14.0 Loaded!     ")
print("==========================================================")
