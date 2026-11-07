import type { IDataObject, IExecuteFunctions, IHttpRequestOptions, ICredentialDataDecryptedObject } from 'n8n-workflow';

export type Operation = 'dispatchHealth' | 'triageCheckin';
export class HahError extends Error {
	constructor(readonly code: string, message: string, readonly status?: number) { super(message); }
}

export function baseUrl(credentials: ICredentialDataDecryptedObject): string {
	let url: URL;
	try { url = new URL(String(credentials.baseUrl)); } catch { throw new HahError('INVALID_URL', 'Enter a valid H@H API URL.'); }
	const local = ['localhost', '127.0.0.1', '[::1]', 'api'].includes(url.hostname);
	if (url.username || url.password || url.search || url.hash ||
		(url.protocol !== 'https:' && !(url.protocol === 'http:' && local && credentials.allowLocalHttp === true))) {
		throw new HahError('UNSAFE_URL', 'Use HTTPS without user info, query or fragment; local HTTP requires explicit demo opt-in.');
	}
	if (typeof credentials.apiKey !== 'string' || !credentials.apiKey.trim() || /[\r\n]/.test(credentials.apiKey)) {
		throw new HahError('INVALID_CREDENTIAL', 'Configure a non-empty internal API key.');
	}
	return url.toString().replace(/\/+$/, '');
}

export function requestOptions(credentials: ICredentialDataDecryptedObject, operation: Operation, eventId?: unknown): IHttpRequestOptions {
	const root = baseUrl(credentials);
	if (operation !== 'dispatchHealth' && operation !== 'triageCheckin') throw new HahError('INVALID_OPERATION', 'Select a supported H@H operation.');
	if (operation === 'triageCheckin' && (typeof eventId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(eventId))) {
		throw new HahError('INVALID_EVENT_ID', 'Event ID must contain 1–128 letters, digits, underscores or hyphens.');
	}
	return {
		url: root + (operation === 'dispatchHealth' ? '/internal/ops/dispatch-health' : '/internal/checkin/triage'),
		method: 'POST', body: operation === 'triageCheckin' ? { event_id: eventId as string } : {},
		json: true, returnFullResponse: true, disableFollowRedirect: true, timeout: 10000,
	};
}

const messages: Record<number, string> = {
	401: 'Internal API authentication failed. Check the credential.',
	403: 'The API denied this operation.',
	404: 'Check-in not found. Use the ID of a stored synthetic check-in.',
	409: 'The API reported a state conflict. Review the backend state before rerunning.',
	422: 'The API rejected the request. Check the event ID and API contract.',
	429: 'The API rate limit was reached. Retry later.',
	503: 'H@H is unavailable or dispatch needs operator review. Check backend health.',
};

function record(value: unknown): Record<string, unknown> | undefined {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

export function safeError(error: unknown): HahError {
	if (error instanceof HahError) return error;
	const e = record(error);
	const response = record(e?.response);
	const raw = response?.status ?? response?.statusCode ?? e?.statusCode ?? e?.httpCode;
	const status = Number(raw);
	if (Number.isInteger(status) && status >= 100 && status <= 599) {
		return new HahError('HTTP_' + status, messages[status] ?? 'The H@H API request failed. Inspect backend logs using approved access.', status);
	}
	// Never retain the original error/cause: HTTP libraries may include request
	// headers, full URLs, credentials, payloads and upstream response bodies.
	return new HahError('TRANSPORT_ERROR', 'H@H could not be reached. Check connectivity and TLS; the outcome may be unknown.');
}

export function mapResponse(operation: Operation, value: unknown, eventId?: unknown): IDataObject {
	const data = record(value);
	const invalid = () => { throw new HahError('INVALID_RESPONSE', 'H@H returned an unexpected response schema.'); };
	if (!data) return invalid();
	if (operation === 'dispatchHealth') {
		const counts = record(data.counts);
		if (data.healthy !== true || data.synthetic_only !== true || data.webhook_ack_is_not_completion !== true || !counts) return invalid();
		const safeCounts: IDataObject = {};
		for (const key of ['PENDING', 'LEASED', 'DELIVERED', 'DEAD']) {
			const count = counts[key];
			if (count === undefined) continue;
			if (typeof count !== 'number' || !Number.isSafeInteger(count) || count < 0) return invalid();
			safeCounts[key] = count;
		}
		return { healthy: true, counts: safeCounts, synthetic_only: true, webhook_ack_is_not_completion: true };
	}
	if (data.event_id !== eventId || data.status !== 'TRIAGED') return invalid();
	if (data.idempotent === true) return { event_id: String(eventId), status: 'TRIAGED', idempotent: true };
	if (!['urgent', 'review'].includes(String(data.priority)) ||
		!['REPORTED_URGENT_SYMPTOM', 'CHECKIN_RECORDED'].includes(String(data.reason_code))) return invalid();
	return { event_id: String(eventId), status: 'TRIAGED', priority: data.priority as string, reason_code: data.reason_code as string };
}

type Request = (options: IHttpRequestOptions) => Promise<unknown>;
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
export async function callApi(request: Request, options: IHttpRequestOptions, operation: Operation,
	eventId?: unknown, retries = 2, wait: (ms: number) => Promise<void> = sleep): Promise<IDataObject> {
	const budget = operation === 'dispatchHealth' ? Math.max(0, Math.min(3, Math.trunc(retries) || 0)) : 0;
	for (let attempt = 0; ; attempt++) {
		let response: Record<string, unknown> | undefined;
		try {
			response = record(await request(options));
			const status = response?.statusCode;
			if (typeof status !== 'number') throw new HahError('INVALID_RESPONSE', 'H@H returned an unexpected HTTP response.');
			if (status !== 200) throw { statusCode: status };
			return mapResponse(operation, response?.body, eventId);
		} catch (error) {
			const safe = safeError(error);
			if (attempt >= budget || ![429, 502, 503, 504].includes(safe.status ?? 0)) throw safe;
			const source = record(record(error)?.response);
			const headers = record(response?.headers) ?? record(source?.headers);
			const retryAfter = headers?.['retry-after'];
			let delay = 250 * 2 ** attempt;
			if (retryAfter !== undefined) {
				const seconds = Number(retryAfter);
				const requested = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(String(retryAfter)) - Date.now();
				// A long server backoff must not be shortened; stop and let the operator reschedule.
				if (Number.isFinite(requested) && requested > 30000) throw safe;
				if (Number.isFinite(requested) && requested >= 0) delay = Math.max(delay, requested);
			}
			await wait(delay);
		}
	}
}

export async function executeRequest(context: IExecuteFunctions, credentials: ICredentialDataDecryptedObject,
	operation: Operation, eventId: unknown, retries: number): Promise<IDataObject> {
	return callApi((options) => context.helpers.httpRequestWithAuthentication.call(context, 'hahApi', options),
		requestOptions(credentials, operation, eventId), operation, eventId, retries);
}
