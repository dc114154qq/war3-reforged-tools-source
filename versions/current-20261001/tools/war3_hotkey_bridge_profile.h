/* The hotkey transport shares the versioned loader configuration ABI. */
typedef struct BridgeProfile {uint32_t version,size,values[11];} BridgeProfile;
__declspec(dllexport) volatile BridgeProfile bridge_profile={1u,52u,{0}};
__declspec(dllexport) const uint32_t bridge_profile_abi[2]={1u,52u};
