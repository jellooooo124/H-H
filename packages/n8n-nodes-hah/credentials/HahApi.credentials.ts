import type { IAuthenticateGeneric, ICredentialType, INodeProperties } from 'n8n-workflow';

export class HahApi implements ICredentialType {
	name = 'hahApi';
	displayName = 'H@H Internal API';
	documentationUrl = 'https://github.com/jellooooo124/H-H/blob/main/packages/n8n-nodes-hah/README.md';
	properties: INodeProperties[] = [
		{ displayName: 'Base URL', name: 'baseUrl', type: 'string', default: 'https://hah.example.invalid', required: true,
			description: 'Trusted H@H API origin, with an optional reverse-proxy path prefix' },
		{ displayName: 'Internal API Key', name: 'apiKey', type: 'string', typeOptions: { password: true }, default: '', required: true },
		{ displayName: 'Allow Local Demo HTTP', name: 'allowLocalHttp', type: 'boolean', default: false,
			description: 'Whether to allow HTTP only for localhost, 127.0.0.1, [::1], or the Compose service api. HTTPS is otherwise required.' },
	];
	authenticate: IAuthenticateGeneric = {
		type: 'generic', properties: { headers: { 'X-Internal-Key': '={{$credentials.apiKey}}' } },
	};
	// Tested by the node's credentialTest method so URL validation and redirect
	// protection are identical when testing credentials and executing workflows.
}
