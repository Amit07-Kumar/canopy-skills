/**
 * RequireWise - Version Configuration
 * Current stable version of the BRD Agent platform.
 * Used for UI display and cache busting.
 */
const APP_VERSION = '1.5';
if (typeof window !== 'undefined') {
    window.APP_VERSION = APP_VERSION;
}
