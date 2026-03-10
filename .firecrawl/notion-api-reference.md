[Skip to main content](https://developers.notion.com/reference/intro#content-area)

[Notion Docs home page![light logo](https://mintcdn.com/notion-demo/y5bW41QcK2WmM1dx/logo/light.svg?fit=max&auto=format&n=y5bW41QcK2WmM1dx&q=85&s=5ede268bf121e5a303275b3084ff3f47)![dark logo](https://mintcdn.com/notion-demo/y5bW41QcK2WmM1dx/logo/dark.svg?fit=max&auto=format&n=y5bW41QcK2WmM1dx&q=85&s=200fbeb606737cfb4fd0191c3c315899)](https://developers.notion.com/)

Search...

⌘KAsk AI

- [View my integrations](https://www.notion.so/profile/integrations)
- [Log in](https://www.notion.com/login?from=marketing&pathname=%2F&tid=dca7da8ee15442a79dc2add103b26604)
- [Get Notion free](https://www.notion.com/signup?from=marketing&pathname=%2F&tid=dca7da8ee15442a79dc2add103b26604)
- [Get Notion free](https://www.notion.com/signup?from=marketing&pathname=%2F&tid=dca7da8ee15442a79dc2add103b26604)

Search...

Navigation

Notion API

Introduction

[Home](https://developers.notion.com/) [Guides](https://developers.notion.com/guides/get-started/getting-started) [API Reference](https://developers.notion.com/reference/intro) [Changelog](https://developers.notion.com/page/changelog) [Examples](https://developers.notion.com/page/examples)

- [Status](https://www.notion-status.com/)
- [Community](https://www.notion.com/community)
- [Blog](https://www.notion.com/blog)

##### Notion API

- [Introduction](https://developers.notion.com/reference/intro)
- [Integration capabilities](https://developers.notion.com/reference/capabilities)
- Webhooks

- [Request limits](https://developers.notion.com/reference/request-limits)
- [Status codes](https://developers.notion.com/reference/status-codes)
- Versioning

##### Objects

- Block

- Page

- [Database](https://developers.notion.com/reference/database)
- Data source

- Comment

- File

- [User](https://developers.notion.com/reference/user)
- [Parent](https://developers.notion.com/reference/parent-object)
- [Emoji](https://developers.notion.com/reference/emoji-object)
- [Unfurl attribute (Link Previews)](https://developers.notion.com/reference/unfurl-attribute-object)

##### Endpoints

- Authentication

- Blocks

- Pages

- Databases

- Data sources

- Databases (deprecated)

- Comments

- File Uploads

- Search

- Users

On this page

- [Conventions](https://developers.notion.com/reference/intro#conventions)
- [JSON conventions](https://developers.notion.com/reference/intro#json-conventions)
- [Code samples & SDKs](https://developers.notion.com/reference/intro#code-samples-%26-sdks)
- [Pagination](https://developers.notion.com/reference/intro#pagination)
- [Supported endpoints](https://developers.notion.com/reference/intro#supported-endpoints)
- [Responses](https://developers.notion.com/reference/intro#responses)
- [Parameters for paginated requests](https://developers.notion.com/reference/intro#parameters-for-paginated-requests)
- [How to send a paginated request](https://developers.notion.com/reference/intro#how-to-send-a-paginated-request)
- [Example: request the next set of query results from a database](https://developers.notion.com/reference/intro#example-request-the-next-set-of-query-results-from-a-database)

Notion API

# Introduction

Copy page

The reference is your key to a comprehensive understanding of the Notion API.

Copy page

Integrations use the API to access Notion’s pages, databases, and users. Integrations can connect services to Notion and build interactive experiences for users within Notion. Using the navigation on the left, you’ll find details for objects and endpoints used in the API.

You need an integration token to interact with the Notion API. You can find an integration token after you create an integration on the integration settings page. If this is your first look at the Notion API, we recommend beginning with the [Getting started guide](https://developers.notion.com/guides/get-started/getting-started) to learn how to create an integration.If you want to work on a specific integration, but can’t access the token, confirm that you are an admin in the associated workspace. You can check inside the Notion UI via `Settings & Members` in the left sidebar. If you’re not an admin in any of your workspaces, you can create a personal workspace for free.

## [​](https://developers.notion.com/reference/intro#conventions) Conventions

The base URL to send all API requests is `https://api.notion.com`. HTTPS is required for all API requests.The Notion API follows RESTful conventions when possible, with most operations performed via `GET`, `POST`, `PATCH`, and `DELETE` requests on page and database resources. Request and response bodies are encoded as JSON.

### [​](https://developers.notion.com/reference/intro#json-conventions) JSON conventions

- Top-level resources have an `"object"` property. This property can be used to determine the type of the resource (e.g. `"database"`, `"user"`, etc.)
- Top-level resources are addressable by a UUIDv4 `"id"` property. You may omit dashes from the ID when making requests to the API, e.g. when copying the ID from a Notion URL.
- Property names are in `snake_case` (not `camelCase` or `kebab-case`).
- Temporal values (dates and datetimes) are encoded in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) strings. Datetimes will include the time value (`2020-08-12T02:12:33.231Z`) while dates will include only the date (`2020-08-12`)
- The Notion API does not support empty strings. To unset a string value for properties like a `url` [Property value object](https://developers.notion.com/reference/property-value-object), for example, use an explicit `null` instead of `""`.

## [​](https://developers.notion.com/reference/intro#code-samples-&-sdks) Code samples & SDKs

Samples requests and responses are shown for each endpoint. Requests are shown using the Notion [JavaScript SDK](https://github.com/makenotion/notion-sdk-js), and [cURL](https://curl.se/). These samples make it easy to copy, paste, and modify as you build your integration.Notion SDKs are open source projects that you can install to easily start building. You may also choose any other language or library that allows you to make HTTP requests.

## [​](https://developers.notion.com/reference/intro#pagination) Pagination

Endpoints that return lists of objects support cursor-based pagination requests. By default, Notion returns ten items per API call. If the number of items in a response from a support endpoint exceeds the default, then an integration can use pagination to request a specific set of the results and/or to limit the number of returned items.

### [​](https://developers.notion.com/reference/intro#supported-endpoints) Supported endpoints

| HTTP method | Endpoint                                                                                          |
| ----------- | ------------------------------------------------------------------------------------------------- |
| GET         | [List all users](https://developers.notion.com/reference/get-users)                               |
| GET         | [Retrieve block children](https://developers.notion.com/reference/get-block-children)             |
| GET         | [Retrieve a comment](https://developers.notion.com/reference/list-comments)                       |
| GET         | [Retrieve a page property item](https://developers.notion.com/reference/retrieve-a-page-property) |
| POST        | [Query a data source](https://developers.notion.com/reference/query-a-data-source)                |
| POST        | [Search](https://developers.notion.com/reference/post-search)                                     |

### [​](https://developers.notion.com/reference/intro#responses) Responses

If an endpoint supports pagination, then the response object contains the below fields.

| Field         | Type                                                                                                              | Description                                                                                                                                                                                                                                                                              |
| ------------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `has_more`    | `boolean`                                                                                                         | Whether the response includes the end of the list. `false` if there are no more results. Otherwise, `true`.                                                                                                                                                                              |
| `next_cursor` | `string`                                                                                                          | A string that can be used to retrieve the next page of results by passing the value as the `start_cursor` [parameter](https://developers.notion.com/reference/intro#parameters-for-paginated-requests) to the same endpoint.<br> Only available when `has_more` is true.                 |
| `object`      | `"list"`                                                                                                          | The constant string `"list"`.                                                                                                                                                                                                                                                            |
| `results`     | `array of objects`                                                                                                | The list, or partial list, of endpoint-specific results. Refer to a [supported endpoint](https://developers.notion.com/reference/intro#supported-endpoints)’s individual documentation for details.                                                                                      |
| `type`        | `"block"`<br>`"comment"`<br>`"database"`<br>`"page"`<br>`"page_or_database"`<br>`"property_item"`<br>`"user"`     | A constant string that represents the type of the objects in `results`.                                                                                                                                                                                                                  |
| `{type}`      | [`paginated list object`](https://developers.notion.com/reference/page-property-values#paginated-page-properties) | An object containing type-specific pagination information. For `property_item`s, the value corresponds to the [paginated page property type](https://developers.notion.com/reference/page-property-values#paginated-page-properties). For all other types, the value is an empty object. |

### [​](https://developers.notion.com/reference/intro#parameters-for-paginated-requests) Parameters for paginated requests

**Parameter location varies by endpoint**`GET` requests accept parameters in the query string.`POST` requests receive parameters in the request body.

| Parameter      | Type     | Description                                                                                                                                                                                                                          |
| -------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `page_size`    | `number` | The number of items from the full list to include in the response. <br>**Default**: `100`<br>**Maximum**: `100`<br> The response may contain fewer than the default number of results.                                               |
| `start_cursor` | `string` | A `next_cursor` value returned in a previous [response](https://developers.notion.com/reference/intro#responses). Treat this as an opaque value. <br> Defaults to `undefined`, which returns results from the beginning of the list. |

### [​](https://developers.notion.com/reference/intro#how-to-send-a-paginated-request) How to send a paginated request

1

[Navigate to header](https://developers.notion.com/reference/intro#)

Send an initial request to the [supported endpoint](https://dev.notion.so/Review-Pagination-documentation-e48701d7465444c7ad79237914aa47cd).

2

[Navigate to header](https://developers.notion.com/reference/intro#)

Retrieve the `next_cursor` value from the response (only available when `has_more` is `true`).

3

[Navigate to header](https://developers.notion.com/reference/intro#)

Send a follow up request to the endpoint that includes the `next_cursor` param in either the query string (for `GET` requests) or in the body params (`POST` requests).

#### [​](https://developers.notion.com/reference/intro#example-request-the-next-set-of-query-results-from-a-database) Example: request the next set of query results from a database

cURL

Report incorrect code

Copy

Ask AI

```
curl --location --request POST 'https://api.notion.com/v1/databases/<database_id>/query' \
--header 'Authorization: Bearer <secret_bot>' \
--header 'Content-Type: application/json' \
--data '{
    "start_cursor": "33e19cb9-751f-4993-b74d-234d67d0d534"
}'
```

[Integration capabilities\\
\\
Next](https://developers.notion.com/reference/capabilities)

⌘I

[instagram](https://www.instagram.com/notionhq) [x](https://twitter.com/NotionHQ) [linkedin](https://www.linkedin.com/company/notionhq) [facebook](https://www.facebook.com/NotionHQ) [youtube](https://www.youtube.com/channel/UCoSvlWS5XcwaSzIcbuJ-Ysg)

[Powered by](https://www.mintlify.com/?utm_campaign=poweredBy&utm_medium=referral&utm_source=notion-demo)
