#include "war3_hotkey_bridge_core.c"
#define HOTKEY_SHARED_BRIDGE 1
#include "war3_hotkey_native_helper.c"
__declspec(dllexport) const uint32_t hotkey_bridge_abi[3]={0x4b485257u,216u,800u};
__declspec(dllexport) uint64_t HotkeyBridgeQuery(void) {
    NativeCommand *command=(NativeCommand *)g_dispatch->work;
    if(!command || command->magic!=WAR3_HOTKEY_MAGIC || command->version!=4 ||
       command->status!=1 || !command->op_count || command->op_count>16)return 0;
    execute_command(command);
    return command->status==WAR3_HOTKEY_STATUS_OK;
}
