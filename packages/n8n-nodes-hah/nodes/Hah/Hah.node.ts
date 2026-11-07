import { NodeConnectionTypes, NodeOperationError } from 'n8n-workflow';
import type { ICredentialTestFunctions, ICredentialsDecrypted, IExecuteFunctions, INodeCredentialTestResult,
	INodeExecutionData, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { callApi, executeRequest, requestOptions, safeError } from './transport';
import type { Operation } from './transport';

export class Hah implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'H@H', name: 'hah', group: ['transform'], version: 1,
		description: 'Coordinate synthetic H@H check-ins and inspect dispatch health',
		defaults: { name: 'H@H' }, inputs: [NodeConnectionTypes.Main], outputs: [NodeConnectionTypes.Main],
		credentials: [{ name: 'hahApi', required: true, testedBy: 'hahCredentialTest' }],
		properties: [
			{ displayName: 'Operation', name: 'operation', type: 'options', noDataExpression: true, default: 'dispatchHealth', options: [
				{ name: 'Get Dispatch Health', value: 'dispatchHealth', action: 'Get dispatch health', description: 'Read queue counts without dispatching jobs' },
				{ name: 'Triage Check-in', value: 'triageCheckin', action: 'Triage a check in', description: 'Ask the backend to process an existing synthetic check-in ID' },
			] },
			{ displayName: 'Event ID', name: 'eventId', type: 'string', default: '', required: true,
				displayOptions: { show: { operation: ['triageCheckin'] } }, description: 'Opaque ID only. Do not pass patient content or a JSON body.' },
			{ displayName: 'Health Check Retries', name: 'retries', type: 'number', default: 2,
				typeOptions: { minValue: 0, maxValue: 3 }, displayOptions: { show: { operation: ['dispatchHealth'] } },
				description: 'Retries after 429/502/503/504 only. Triage is never automatically retried by this node.' },
		],
	};

	methods = { credentialTest: {
		async hahCredentialTest(this: ICredentialTestFunctions, credential: ICredentialsDecrypted): Promise<INodeCredentialTestResult> {
			try {
				const options = requestOptions(credential.data ?? {}, 'dispatchHealth');
				// ICredentialTestFunctions exposes the legacy request adapter, not the execute helper.
				await callApi((request) => this.helpers.request({
					uri: request.url, method: request.method, body: request.body, json: true,
					headers: { 'X-Internal-Key': credential.data?.apiKey },
					followRedirect: false, followAllRedirects: false, resolveWithFullResponse: true, timeout: 10000,
				}), options, 'dispatchHealth', undefined, 0);
				return { status: 'OK', message: 'Authenticated; dispatch health is good.' };
			} catch (error) { return { status: 'Error', message: safeError(error).message }; }
		},
	} };

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const output: INodeExecutionData[] = [];
		for (let i = 0; i < items.length; i++) {
			try {
				const operation = this.getNodeParameter('operation', i) as Operation;
				const eventId = operation === 'triageCheckin' ? this.getNodeParameter('eventId', i) : undefined;
				const retries = operation === 'dispatchHealth' ? Number(this.getNodeParameter('retries', i, 2)) : 0;
				const credentials = await this.getCredentials('hahApi');
				const json = await executeRequest(this, credentials, operation, eventId, retries);
				output.push({ json, pairedItem: { item: i } });
			} catch (error) {
				const safe = safeError(error);
				if (!this.continueOnFail()) throw new NodeOperationError(this.getNode(), safe.message, { itemIndex: i, description: safe.code });
				output.push({ json: { error: safe.message, code: safe.code }, pairedItem: { item: i } });
			}
		}
		return [output];
	}
}
